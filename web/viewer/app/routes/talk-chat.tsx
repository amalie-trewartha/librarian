import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, SendHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

import { useControlsEnabled } from "~/components/thinker-controls";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { LoadingDots } from "~/components/ui/loading-dots";
import { fetchChat, fetchThinkers, sendChat } from "~/lib/api";
import type { ChatMessage } from "~/lib/types";
import { getPwaName, pwaSender, setLastIdentity } from "~/lib/pwa";
import { cn } from "~/lib/utils";

export function meta() {
  return [{ title: "Audel" }];
}

function messageTime(ts: string | null): string {
  if (!ts) return "";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function Bubble({ message, mine }: { message: ChatMessage; mine: boolean }) {
  return (
    <div className={cn("flex", mine ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3.5 py-2",
          mine
            ? "rounded-br-md bg-primary text-primary-foreground"
            : "rounded-bl-md border bg-card"
        )}
      >
        {mine ? (
          <div className="whitespace-pre-wrap break-words text-sm">
            {message.content}
          </div>
        ) : (
          <div className="prose prose-sm max-w-none break-words dark:prose-invert">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
        <div
          className={cn(
            "mt-0.5 text-right font-mono text-[10px]",
            mine ? "text-primary-foreground/60" : "text-muted-foreground"
          )}
        >
          {messageTime(message.ts)}
        </div>
      </div>
    </div>
  );
}

export default function TalkChat() {
  const { identityId = "" } = useParams();
  const navigate = useNavigate();
  const controlsEnabled = useControlsEnabled();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const name = getPwaName();
  useEffect(() => {
    if (!name) navigate("/talk", { replace: true });
    else setLastIdentity(identityId);
  }, [name, identityId, navigate]);
  const myName = name ? pwaSender(name) : "";

  const { data: chat, isLoading } = useQuery({
    queryKey: ["chat", identityId, myName],
    queryFn: () => fetchChat(identityId, 200, myName),
    refetchInterval: 2000,
    enabled: !!myName,
  });

  const { data: thinkerStatus } = useQuery({
    queryKey: ["thinkers", identityId],
    queryFn: () => fetchThinkers(identityId),
    refetchInterval: 5000,
  });
  const dispatcherRunning = thinkerStatus?.dispatcher.running ?? true;

  const messages = chat?.messages ?? [];
  const messageCount = messages.length;
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messageCount]);

  const sendMutation = useMutation({
    mutationFn: (content: string) => sendChat(identityId, content, myName),
    onSuccess: () => {
      setDraft("");
      queryClient.invalidateQueries({ queryKey: ["chat", identityId, myName] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const identityName = chat?.identity.name ?? identityId.split("~").pop();

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center gap-1 border-b px-2 pb-2 pt-[calc(env(safe-area-inset-top)+0.5rem)]">
        <Link
          to="/talk?pick=1"
          className="flex h-9 w-9 items-center justify-center rounded-full active:bg-accent"
          aria-label="Back to identity list"
        >
          <ChevronLeft className="size-5" />
        </Link>
        <div className="flex flex-1 items-center gap-2">
          <span className="font-medium">{identityName}</span>
          <span
            className={cn(
              "inline-block h-2 w-2 rounded-full",
              chat?.live ? "bg-green-500" : "bg-muted-foreground/30"
            )}
            title={chat?.live ? "live" : "idle"}
          />
        </div>
        <span className="pr-2 font-mono text-[10px] text-muted-foreground">
          {myName}
        </span>
      </header>

      {!dispatcherRunning && (
        <div className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          {identityName} is asleep (thinkers stopped) — messages will wait
          until it wakes.
        </div>
      )}

      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {isLoading ? (
          <div className="flex justify-center py-10">
            <LoadingDots />
          </div>
        ) : messages.length === 0 ? (
          <div className="py-10 text-center text-sm text-muted-foreground">
            No messages yet. Say hello.
          </div>
        ) : (
          messages.map((message, idx) => (
            <Bubble
              key={message.step_id ?? idx}
              message={message}
              mine={message.from === myName}
            />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {controlsEnabled && (
        <form
          className="flex items-center gap-2 border-t px-3 pt-2 pb-[calc(env(safe-area-inset-bottom)+0.5rem)]"
          onSubmit={(event) => {
            event.preventDefault();
            const content = draft.trim();
            if (content && !sendMutation.isPending) sendMutation.mutate(content);
          }}
        >
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={`Message ${identityName}…`}
            className="h-10 flex-1 rounded-full px-4"
            autoComplete="off"
          />
          <Button
            type="submit"
            size="icon"
            className="h-10 w-10 shrink-0 rounded-full"
            disabled={sendMutation.isPending || !draft.trim()}
            aria-label="Send"
          >
            <SendHorizontal className="size-4" />
          </Button>
        </form>
      )}
    </div>
  );
}
