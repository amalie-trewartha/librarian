import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Info, KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router";
import { toast } from "sonner";

import { IdentityTabs } from "~/components/identity-tabs";
import { ModelConfigSection } from "~/components/model-config";
import { useControlsEnabled } from "~/components/thinker-controls";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { Checkbox } from "~/components/ui/checkbox";
import { Input } from "~/components/ui/input";
import { LoadingDots } from "~/components/ui/loading-dots";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "~/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "~/components/ui/table";
import {
  deleteEnvVar,
  exportJobDownloadUrl,
  fetchExportJob,
  fetchIdentityEnv,
  fetchIdentityStatus,
  putEnvVar,
  startExportJob,
} from "~/lib/api";
import type { EnvEntry } from "~/lib/types";

export function meta() {
  return [{ title: "Headlong · config" }];
}

function useEnvMutations(identityId: string) {
  const queryClient = useQueryClient();
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["env", identityId] });
  const save = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      putEnvVar(identityId, key, value),
    onSuccess: (entry) => {
      toast.success(`Saved ${entry.key}`);
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const remove = useMutation({
    mutationFn: (key: string) => deleteEnvVar(identityId, key),
    onSuccess: (result) => {
      toast.success(`Removed ${result.key}`);
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  return { save, remove };
}

function ValueDisplay({ entry }: { entry: EnvEntry }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-xs">
      {entry.secret && (
        <KeyRound className="size-3 shrink-0 text-muted-foreground" />
      )}
      {entry.value || <span className="text-muted-foreground">(empty)</span>}
    </span>
  );
}

function EnvRow({
  identityId,
  entry,
}: {
  identityId: string;
  entry: EnvEntry;
}) {
  const controlsEnabled = useControlsEnabled();
  const { save, remove } = useEnvMutations(identityId);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  return (
    <TableRow>
      <TableCell className="font-mono text-xs font-medium">{entry.key}</TableCell>
      <TableCell>
        {editing ? (
          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate(
                { key: entry.key, value: draft },
                { onSuccess: () => setEditing(false) }
              );
            }}
          >
            <Input
              autoFocus
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={
                entry.secret ? "enter new value (replaces current)" : entry.value
              }
              className="h-8 flex-1 font-mono text-xs"
            />
            <Button type="submit" size="sm" disabled={save.isPending}>
              Save
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setEditing(false)}
            >
              Cancel
            </Button>
          </form>
        ) : (
          <ValueDisplay entry={entry} />
        )}
      </TableCell>
      <TableCell className="text-right">
        {controlsEnabled && !editing && (
          <div className="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="icon-sm"
              title={`Edit ${entry.key}`}
              onClick={() => {
                setDraft(entry.secret ? "" : entry.value);
                setEditing(true);
              }}
            >
              <Pencil className="size-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              title={`Remove ${entry.key}`}
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Remove ${entry.key} from this identity's .env?`))
                  remove.mutate(entry.key);
              }}
            >
              <Trash2 className="size-3" />
            </Button>
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

function AddVarForm({
  identityId,
  prefillKey,
  onDone,
}: {
  identityId: string;
  prefillKey: string;
  onDone: () => void;
}) {
  const { save } = useEnvMutations(identityId);
  const [key, setKey] = useState(prefillKey);
  const [value, setValue] = useState("");

  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!key.trim()) return;
        save.mutate(
          { key: key.trim(), value },
          {
            onSuccess: () => {
              setKey("");
              setValue("");
              onDone();
            },
          }
        );
      }}
    >
      <Input
        value={key}
        onChange={(event) => setKey(event.target.value)}
        placeholder="VARIABLE_NAME"
        pattern="[A-Za-z_][A-Za-z0-9_]*"
        title="letters, digits, underscores"
        className="h-8 w-56 font-mono text-xs"
      />
      <Input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="value"
        className="h-8 flex-1 font-mono text-xs"
      />
      <Button type="submit" size="sm" disabled={save.isPending || !key.trim()}>
        <Plus className="size-3" />
        Add
      </Button>
    </form>
  );
}

function formatBytes(n: number): string {
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function ExportSection({ identityId }: { identityId: string }) {
  const [soulOnly, setSoulOnly] = useState(false);
  const [slim, setSlim] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);

  // The archive is built in the background; poll until it is ready. A
  // synchronous download of a big mind log sat silent for a minute and
  // then died at Cloudflare's 100s limit, which looked like nothing at all.
  const job = useQuery({
    queryKey: ["export-job", jobId],
    queryFn: () => fetchExportJob(jobId!),
    enabled: jobId !== null,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1500 : false),
  });
  const start = useMutation({
    mutationFn: () => startExportJob(identityId, { soulOnly, slim }),
    onSuccess: (j) => setJobId(j.job_id),
    onError: (e: Error) => toast.error(`Export failed to start: ${e.message}`),
  });

  const status = job.data?.status;
  const running = start.isPending || status === "running";
  return (
    <section className="mt-8">
      <div className="mb-2 flex items-baseline gap-3">
        <h2 className="font-mono text-xs font-medium uppercase tracking-wider text-muted-foreground">
          export
        </h2>
        <span className="text-[11px] text-muted-foreground">
          Snapshot this identity as a portable .tgz — import it on another
          Headlong dash (or with `identity import`). Secrets (.env) and runtime
          state never leave the box.
        </span>
      </div>
      <div className="flex flex-col gap-3 rounded-lg border p-3">
        <div className="flex flex-wrap items-center gap-4">
          <Button
            variant="outline"
            size="sm"
            disabled={running}
            onClick={() => start.mutate()}
          >
            {running ? <LoadingDots /> : <Download className="size-3" />}
            {running ? "Building" : "Build export"}
          </Button>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Checkbox
              checked={slim}
              disabled={running}
              onCheckedChange={(checked) => setSlim(checked === true)}
            />
            slim
            <Tooltip>
              <TooltipTrigger asChild>
                <Info className="size-3 shrink-0 cursor-help" />
              </TooltipTrigger>
              <TooltipContent className="max-w-sm text-xs">
                <p className="mb-1">
                  <b>Slim</b> (on): every step is kept, but the two fields that
                  repeat in each step — the rendered prompt context and the
                  shellm launch command line — are cut to a short head plus
                  &ldquo;…[truncated N chars]&rdquo;. API keys are replaced with
                  [REDACTED:…]. Thoughts, messages, reasoning and shell output
                  travel whole. A 1 GB mind log becomes about 17 MB and still
                  imports.
                </p>
                <p>
                  <b>Fat</b> (off): a byte-for-byte copy of the trajectories,
                  including any keys that leaked into them. Use it for a real
                  backup or to replay exact prompts; roughly a third of the raw
                  size once gzipped.
                </p>
              </TooltipContent>
            </Tooltip>
          </label>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Checkbox
              checked={soulOnly}
              disabled={running}
              onCheckedChange={(checked) => setSoulOnly(checked === true)}
            />
            soul only — skip trajectories (memories, thinkers, and skills; the
            import starts a fresh mind log)
          </label>
        </div>
        {job.data && (
          <div className="flex flex-wrap items-center gap-3 text-xs">
            {status === "running" && (
              <span className="text-muted-foreground">
                Building on the server… {Math.round(job.data.seconds)}s. Big
                mind logs take a minute or two; you can leave this page and
                come back.
              </span>
            )}
            {status === "done" && (
              <>
                <Button size="sm" asChild>
                  <a href={exportJobDownloadUrl(job.data)} download={job.data.filename ?? undefined}>
                    <Download className="size-3" />
                    Download {job.data.filename}
                    {job.data.size !== null && ` (${formatBytes(job.data.size)})`}
                  </a>
                </Button>
                <span className="text-muted-foreground">
                  built in {Math.round(job.data.seconds)}s
                </span>
              </>
            )}
            {status === "failed" && (
              <span className="text-destructive">
                Export failed: {job.data.error ?? "unknown error"}
              </span>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

export default function ConfigPage() {
  const { identityId = "" } = useParams();
  const controlsEnabled = useControlsEnabled();
  const [prefillKey, setPrefillKey] = useState("");

  const { data: status } = useQuery({
    queryKey: ["status", identityId],
    queryFn: () => fetchIdentityStatus(identityId),
    refetchInterval: 5000,
  });

  const { data: env, isLoading } = useQuery({
    queryKey: ["env", identityId],
    queryFn: () => fetchIdentityEnv(identityId),
  });

  if (isLoading || !env) {
    return (
      <div className="flex justify-center py-20">
        <LoadingDots />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-7xl px-4">
      <IdentityTabs
        identityId={identityId}
        live={status?.live ?? false}
        active="config"
      />
      <div className="mx-auto w-full max-w-4xl">

      <ModelConfigSection identityId={identityId} env={env} />

      <section className="mb-8">
        <div className="mb-2 flex items-baseline gap-3">
          <h2 className="font-mono text-xs font-medium uppercase tracking-wider text-muted-foreground">
            identity .env
          </h2>
          <span className="text-[11px] text-muted-foreground">{env.note}</span>
        </div>
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-64">Variable</TableHead>
                <TableHead>Value</TableHead>
                <TableHead className="w-24 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {env.env.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={3}
                    className="py-6 text-center text-sm text-muted-foreground"
                  >
                    No identity-specific variables yet.
                  </TableCell>
                </TableRow>
              )}
              {env.env.map((entry) => (
                <EnvRow key={entry.key} identityId={identityId} entry={entry} />
              ))}
            </TableBody>
          </Table>
        </div>
        {controlsEnabled && (
          <div className="mt-3">
            <AddVarForm
              key={prefillKey}
              identityId={identityId}
              prefillKey={prefillKey}
              onDone={() => setPrefillKey("")}
            />
          </div>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-baseline gap-3">
          <h2 className="font-mono text-xs font-medium uppercase tracking-wider text-muted-foreground">
            inherited from serve root .env
          </h2>
          <span className="text-[11px] text-muted-foreground">
            Applies to every identity; add a variable above to override it here.
          </span>
        </div>
        <div className="rounded-lg border">
          <Table>
            <TableBody>
              {env.inherited.length === 0 && (
                <TableRow>
                  <TableCell className="py-6 text-center text-sm text-muted-foreground">
                    No .env at the serve root.
                  </TableCell>
                </TableRow>
              )}
              {env.inherited.map((entry) => (
                <TableRow key={entry.key}>
                  <TableCell className="w-64 font-mono text-xs">
                    {entry.key}
                  </TableCell>
                  <TableCell>
                    <ValueDisplay entry={entry} />
                    {entry.overridden && (
                      <Badge variant="outline" className="ml-2 text-[10px]">
                        overridden
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="w-24 text-right">
                    {controlsEnabled && !entry.overridden && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setPrefillKey(entry.key)}
                      >
                        Override
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <ExportSection identityId={identityId} />
      </div>
    </div>
  );
}
