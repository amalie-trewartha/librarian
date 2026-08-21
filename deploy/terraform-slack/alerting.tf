# Box-down alerting: EC2 status-check alarms -> SNS -> Lambda -> Slack.
#
# Born from the 2026-08-13 incident: headlong-web OOM-thrash took the whole
# box off the network at 09:10 UTC and nothing noticed for 13 hours — the
# box's own Slack alert scripts can't report the box being dark. These
# alarms watch from outside:
#
#   - instance check (OS hung / network dead)  -> notify + auto-REBOOT
#   - system check   (AWS hardware failure)    -> notify + auto-RECOVER
#
# Auto-reboot is safe against loops (alarm actions fire once per state
# transition, not per period) and only became safe at all once the boot
# bootstrap deadlock was fixed (headlong-thinkers@.service After= edge) —
# before that, a reboot came up with the persona wedged.
#
# The Lambda reads SLACK_BOT_TOKEN + SHELLM_ALERT_CHANNEL from the same
# SSM env parameter the box bootstraps from, so alerts land in the
# existing alert channel with no extra secret. Optional email fallback
# via var.alert_email (SNS sends a confirmation mail on first apply).

resource "aws_sns_topic" "alerts" {
  name = "shellm-${var.subdomain}-alerts"
}

resource "aws_cloudwatch_metric_alarm" "instance_check" {
  alarm_name        = "shellm-${var.subdomain}-instance-check"
  alarm_description = "OS-level reachability lost on the shellm-${var.subdomain} box (hang, OOM thrash, network dead). Auto-reboots after 3 failed minutes."

  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_Instance"
  dimensions          = { InstanceId = aws_instance.shellm.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  # Deliberate stops (deploy/scripts/stop) stop the metric stream entirely;
  # "missing" parks the alarm in INSUFFICIENT_DATA instead of firing.
  treat_missing_data = "missing"

  alarm_actions = [
    aws_sns_topic.alerts.arn,
    "arn:aws:automate:${var.aws_region}:ec2:reboot",
  ]
  ok_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "system_check" {
  alarm_name        = "shellm-${var.subdomain}-system-check"
  alarm_description = "AWS host hardware failure under the shellm-${var.subdomain} box. Auto-recovers to new hardware (same instance ID, IP, and EBS)."

  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  dimensions          = { InstanceId = aws_instance.shellm.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "missing"

  alarm_actions = [
    aws_sns_topic.alerts.arn,
    "arn:aws:automate:${var.aws_region}:ec2:recover",
  ]
  ok_actions = [aws_sns_topic.alerts.arn]
}

# --- SNS -> Slack Lambda ----------------------------------------------------

data "archive_file" "slack_alert" {
  type        = "zip"
  source_file = "${path.module}/lambda/slack_alert.py"
  output_path = "${path.module}/lambda/slack_alert.zip"
}

resource "aws_iam_role" "slack_alert" {
  name_prefix = "shellm-alert-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "slack_alert" {
  name_prefix = "shellm-alert-"
  role        = aws_iam_role.slack_alert.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.env_parameter}"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "slack_alert" {
  function_name    = "shellm-${var.subdomain}-alert-to-slack"
  role             = aws_iam_role.slack_alert.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "slack_alert.handler"
  filename         = data.archive_file.slack_alert.output_path
  source_code_hash = data.archive_file.slack_alert.output_base64sha256
  timeout          = 20

  environment {
    variables = {
      ENV_PARAMETER = var.env_parameter
    }
  }
}

resource "aws_lambda_permission" "sns" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.slack_alert.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts.arn
}

resource "aws_sns_topic_subscription" "slack" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.slack_alert.arn
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
