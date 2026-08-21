# terminal_bench2_eval/

Harness and results for evaluating shellm and Headlong on
[Terminal-Bench 2](https://www.tbench.ai/) via Harbor. The
`harbor_*_agent.py` and `harbor_*_environment.py` files adapt shellm and
Headlong to Harbor's agent and environment interfaces, and
`harbor_assets/` holds the run scripts and prompt template.

The `*_report*.md` files are the write-ups from past eval runs, and
[failure_analysis.md](failure_analysis.md) digs into what went wrong on
failed tasks.
