import {
  FormEvent,
  KeyboardEvent,
  type ReactNode,
  type ComponentPropsWithoutRef,
  type CSSProperties,
  memo,
  MouseEvent,
  useEffect,
  useRef,
  useState
} from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  artifactUrl,
  createSession,
  deleteSession,
  fetchModelCatalog,
  fetchSession,
  fetchSessions,
  streamMessage,
  updateSessionDatabase,
  updateSessionTitle,
  updateSessionModel
} from "./api";
import type {
  ChatArtifact,
  ChatMessage,
  DatabaseBackend,
  ModelCatalogEntry,
  ModelCatalogResponse,
  ModelProvider,
  SessionDetail,
  SessionMetadata,
  SessionSummary
} from "./types";

const starterPrompts = [
  "Summarize the current architecture and tell me what to refactor first.",
  "Help me plan the next frontend milestone from the existing codebase.",
  "Draft a concise product brief for Ask Jeremy."
];

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

function formatSessionTileTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

function messageAuthorLabel(role: ChatMessage["role"]): string {
  return role === "user" ? "You" : "Jeremy";
}

function databaseLabel(databaseBackend: DatabaseBackend): string {
  return databaseBackend === "snowflake" ? "Snowflake" : "SQLite";
}

function sessionMonogram(title: string): string {
  const trimmed = title.trim();
  if (!trimmed) {
    return "AJ";
  }

  return trimmed.slice(0, 2).toUpperCase();
}

type PlanItemStatus = "not started" | "in progress" | "completed";

type PlanItem = {
  key: string;
  action: string;
  status: PlanItemStatus;
};

type StreamingState = {
  assistantMessageId: string;
  statusLine: string;
  planItems: PlanItem[];
};

const EMPTY_PLAN_ITEMS: PlanItem[] = [];
const STATUS_ORDER: PlanItemStatus[] = ["not started", "in progress", "completed"];
const PLAN_HEADER_PATTERN =
  /^\s*(?:#{1,6}\s*)?\**\s*plan\s*\**\s*:?\s*$/i;
const PLAN_ITEM_PATTERN =
  /^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*(?:[-–—]|\||\()\s*(not started|in progress|completed)\s*\)?\s*$/i;

type LogEntryBase = { id: string; timestamp: number };

type LogEntry =
  | LogEntryBase & { kind: "reasoning"; content: string }
  | LogEntryBase & { kind: "node_lifecycle"; nodeName: string; phase: "started" | "finished"; error: string | null; details: Record<string, unknown> }
  | LogEntryBase & { kind: "mcp_tool_call"; serverName: string; toolName: string };

type RightPanelState =
  | { mode: "artifacts"; messageId: string; messageCreatedAt: string; artifacts: ChatArtifact[] }
  | { mode: "logs"; messageId: string };

type ArtifactPanelResizeState = {
  startX: number;
  startWidth: number;
};

const DEFAULT_ARTIFACT_PANEL_WIDTH = 448;
const MIN_ARTIFACT_PANEL_WIDTH = 320;
const MAX_ARTIFACT_PANEL_WIDTH = 760;

export default function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);
  const [modelCatalog, setModelCatalog] = useState<ModelCatalogResponse | null>(null);
  const [draft, setDraft] = useState("");
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isUpdatingModel, setIsUpdatingModel] = useState(false);
  const [isUpdatingDatabase, setIsUpdatingDatabase] = useState(false);
  const [sessionActionId, setSessionActionId] = useState<string | null>(null);
  const [openSessionMenuId, setOpenSessionMenuId] = useState<string | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const [messagePlans, setMessagePlans] = useState<Record<string, PlanItem[]>>({});
  const [rightPanel, setRightPanel] = useState<RightPanelState | null>(null);
  const [messageLogs, setMessageLogs] = useState<Record<string, LogEntry[]>>({});
  const [isSessionRailCollapsed, setIsSessionRailCollapsed] = useState(false);
  const [artifactPanelWidth, setArtifactPanelWidth] = useState(DEFAULT_ARTIFACT_PANEL_WIDTH);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const artifactPanelResizeRef = useRef<ArtifactPanelResizeState | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  const isRightPanelOpen = rightPanel !== null;

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeSession?.session.id, activeSession?.messages.length]);

  useEffect(() => {
    if (!editingSessionId) {
      return;
    }

    renameInputRef.current?.focus();
    renameInputRef.current?.select();
  }, [editingSessionId]);

  useEffect(() => {
    function handleWindowClick(): void {
      setOpenSessionMenuId(null);
    }

    window.addEventListener("click", handleWindowClick);
    return () => window.removeEventListener("click", handleWindowClick);
  }, []);

  useEffect(() => {
    function handlePointerMove(event: globalThis.MouseEvent): void {
      const resizeState = artifactPanelResizeRef.current;
      if (!resizeState) {
        return;
      }

      const nextWidth = clampArtifactPanelWidth(
        resizeState.startWidth + (resizeState.startX - event.clientX)
      );
      setArtifactPanelWidth(nextWidth);
    }

    function handlePointerUp(): void {
      artifactPanelResizeRef.current = null;
      document.body.classList.remove("artifact-panel-resizing");
    }

    window.addEventListener("mousemove", handlePointerMove);
    window.addEventListener("mouseup", handlePointerUp);
    return () => {
      window.removeEventListener("mousemove", handlePointerMove);
      window.removeEventListener("mouseup", handlePointerUp);
      document.body.classList.remove("artifact-panel-resizing");
    };
  }, []);

  async function bootstrap(): Promise<void> {
    setIsBootstrapping(true);
    setStreaming(null);
    setMessagePlans({});
    setRightPanel(null);
    setMessageLogs({});
    setError(null);
    try {
      const [sessionList, catalog] = await Promise.all([
        fetchSessions(),
        fetchModelCatalog()
      ]);

      setModelCatalog(catalog);
      setSessions(sessionList);

      if (sessionList.length > 0) {
        const detail = await fetchSession(sessionList[0].id);
        setActiveSession(detail);
      } else {
        const created = await createSession(
          undefined,
          catalog.default_provider,
          catalog.default_model_name
        );
        setSessions([created.session]);
        setActiveSession({
          session: created.session,
          messages: created.messages
        });
      }
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    } finally {
      setIsBootstrapping(false);
    }
  }

  async function handleSelectSession(sessionId: string): Promise<void> {
    setStreaming(null);
    setMessagePlans({});
    setRightPanel(null);
    setMessageLogs({});
    setError(null);
    try {
      const detail = await fetchSession(sessionId);
      setActiveSession(detail);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    }
  }

  async function handleNewChat(): Promise<void> {
    setStreaming(null);
    setMessagePlans({});
    setRightPanel(null);
    setMessageLogs({});
    setError(null);
    try {
      const created = await createDefaultSession();
      setSessions((current) => [created.session, ...current]);
      setActiveSession({
        session: created.session,
        messages: created.messages
      });
      setDraft("");
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    }
  }

  function handleStartRenameSession(session: SessionSummary): void {
    setOpenSessionMenuId(null);
    setEditingSessionId(session.id);
    setRenameDraft(session.title);
  }

  function handleCancelRenameSession(): void {
    setEditingSessionId(null);
    setRenameDraft("");
  }

  function handleOpenArtifactPanel(message: ChatMessage): void {
    if (message.role !== "assistant" || message.artifacts.length === 0) {
      return;
    }

    setRightPanel({
      mode: "artifacts",
      messageId: message.id,
      messageCreatedAt: message.created_at,
      artifacts: message.artifacts,
    });
  }

  function handleCloseRightPanel(): void {
    setRightPanel(null);
  }

  function handleOpenLogPanel(messageId: string): void {
    setRightPanel({ mode: "logs", messageId });
  }

  function handleToggleSessionRail(): void {
    setOpenSessionMenuId(null);
    setEditingSessionId(null);
    setRenameDraft("");
    setIsSessionRailCollapsed((current) => !current);
  }

  function handleStartArtifactResize(event: MouseEvent<HTMLDivElement>): void {
    artifactPanelResizeRef.current = {
      startX: event.clientX,
      startWidth: artifactPanelWidth,
    };
    document.body.classList.add("artifact-panel-resizing");
    event.preventDefault();
  }

  async function handleRenameSession(session: SessionSummary): Promise<void> {
    const normalized = renameDraft.trim();
    if (!normalized) {
      handleCancelRenameSession();
      return;
    }

    if (!normalized || normalized === session.title) {
      handleCancelRenameSession();
      return;
    }

    setSessionActionId(session.id);
    setError(null);
    try {
      const updatedSession = await updateSessionTitle(session.id, normalized);
      applySessionMetadataUpdate(updatedSession);
      handleCancelRenameSession();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    } finally {
      setSessionActionId(null);
    }
  }

  async function handleDeleteSession(session: SessionSummary): Promise<void> {
    setOpenSessionMenuId(null);
    const confirmed = window.confirm(`Delete "${session.title}"? This cannot be undone.`);
    if (!confirmed) {
      return;
    }

    setSessionActionId(session.id);
    setError(null);
    try {
      await deleteSession(session.id);
      const remainingSessions = sessions.filter((item) => item.id !== session.id);
      setSessions(remainingSessions);

      if (activeSession?.session.id === session.id) {
        if (remainingSessions.length > 0) {
          const nextSession = await fetchSession(remainingSessions[0].id);
          setActiveSession(nextSession);
        } else {
          const created = await createDefaultSession();
          setSessions([created.session]);
          setActiveSession({
            session: created.session,
            messages: created.messages
          });
        }
      }
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    } finally {
      setSessionActionId(null);
    }
  }

  async function handleProviderChange(nextProvider: ModelProvider): Promise<void> {
    if (!activeSession || !modelCatalog || isUpdatingModel || isSending) {
      return;
    }

    const availableModels = getModelsForProvider(modelCatalog.models, nextProvider);
    if (availableModels.length === 0) {
      return;
    }

    await persistSessionModel(nextProvider, availableModels[0].model_name);
  }

  async function handleModelChange(nextModelName: string): Promise<void> {
    if (!activeSession || isUpdatingModel || isUpdatingDatabase || isSending) {
      return;
    }

    await persistSessionModel(activeSession.session.model_provider, nextModelName);
  }

  async function persistSessionModel(
    modelProvider: ModelProvider,
    modelName: string
  ): Promise<void> {
    if (!activeSession) {
      return;
    }

    setIsUpdatingModel(true);
    setError(null);
    try {
      const updatedSession = await updateSessionModel(
        activeSession.session.id,
        modelProvider,
        modelName
      );
      applySessionMetadataUpdate(updatedSession);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    } finally {
      setIsUpdatingModel(false);
    }
  }

  async function handleDatabaseChange(nextDatabaseBackend: DatabaseBackend): Promise<void> {
    if (!activeSession || isUpdatingDatabase || isUpdatingModel || isSending) {
      return;
    }

    setIsUpdatingDatabase(true);
    setError(null);
    try {
      const updatedSession = await updateSessionDatabase(
        activeSession.session.id,
        nextDatabaseBackend
      );
      applySessionMetadataUpdate(updatedSession);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    } finally {
      setIsUpdatingDatabase(false);
    }
  }

  async function handleSend(event?: FormEvent): Promise<void> {
    event?.preventDefault();
    if (!activeSession || !draft.trim() || isSending) {
      return;
    }

    const sessionId = activeSession.session.id;
    const content = draft.trim();
    setDraft("");
    setIsSending(true);
    setError(null);
    const abortController = new AbortController();
    streamAbortRef.current = abortController;

    const optimisticUserMessage: ChatMessage = {
      id: `local-user-${crypto.randomUUID()}`,
      role: "user",
      content,
      created_at: new Date().toISOString(),
      artifacts: []
    };
    const optimisticAssistantMessage: ChatMessage = {
      id: `local-assistant-${crypto.randomUUID()}`,
      role: "assistant",
      content: "",
      created_at: new Date().toISOString(),
      artifacts: []
    };

    setActiveSession((current) =>
      current
        ? {
            ...current,
            messages: [
              ...current.messages,
              optimisticUserMessage,
              optimisticAssistantMessage
            ]
          }
        : current
    );
    setStreaming({
      assistantMessageId: optimisticAssistantMessage.id,
      statusLine: "Waiting for the model response",
      planItems: []
    });

    let accumulatedContent = "";
    let activatedSkillNames: string[] = [];
    let currentPlanItems: PlanItem[] = [];
    let currentLogEntries: LogEntry[] = [];
    let logSeq = 0;

    function pushLogEntry(entry: Omit<LogEntry, "id" | "timestamp">): void {
      logSeq += 1;
      const full = { ...entry, id: `log-${logSeq}`, timestamp: Date.now() } as LogEntry;
      currentLogEntries = [...currentLogEntries, full];
      const snapshot = currentLogEntries;
      setMessageLogs((prev) => ({ ...prev, [optimisticAssistantMessage.id]: snapshot }));
    }

    const updateOptimisticAssistant = (
      updater: (message: ChatMessage) => ChatMessage
    ): void => {
      setActiveSession((current) =>
        current
          ? {
              ...current,
              messages: current.messages.map((message) =>
                message.id === optimisticAssistantMessage.id
                  ? updater(message)
                  : message
              )
            }
          : current
      );
    };

    try {
      let didComplete = false;
      let streamErrorMessage: string | null = null;

      await streamMessage(sessionId, content, (eventName, payload) => {
        if (eventName === "assistant_delta") {
          const delta = String(
            (payload as { delta?: unknown }).delta ?? ""
          );
          if (!delta) {
            return;
          }

          accumulatedContent += delta;
          updateOptimisticAssistant((message) => ({
            ...message,
            content: message.content + delta
          }));

          const parsedPlan = parsePlanItemsFromContent(accumulatedContent);
          if (parsedPlan.length > 0) {
            currentPlanItems = mergePlans(currentPlanItems, parsedPlan);
            const nextPlan = currentPlanItems;
            setStreaming((current) =>
              current ? { ...current, planItems: nextPlan } : current
            );
          }
          return;
        }

        if (eventName === "task_started") {
          const taskName = String((payload as { name?: unknown }).name ?? "");
          // Capture intermediate reasoning before call_model resets content
          if (taskName === "call_model" && accumulatedContent.trim()) {
            pushLogEntry({ kind: "reasoning", content: accumulatedContent.trim() });
          }
          // Each call_model invocation is a fresh generation — drop any
          // pre-tool-call draft so the streamed text matches the final reply.
          // Plan items persist across resets so their in-place status updates.
          if (taskName === "call_model") {
            accumulatedContent = "";
            updateOptimisticAssistant((message) => ({ ...message, content: "" }));
          }
          pushLogEntry({ kind: "node_lifecycle", nodeName: taskName, phase: "started", error: null, details: {} });
          setStreamingStatus(describeTaskStatus(taskName, "started"));
          return;
        }

        if (eventName === "task_finished") {
          const taskName = String((payload as { name?: unknown }).name ?? "");
          const errorMessage = (payload as { error?: unknown }).error;
          const errorStr = typeof errorMessage === "string" ? errorMessage : null;
          const taskDetails = (payload as { details?: Record<string, unknown> }).details ?? {};
          pushLogEntry({ kind: "node_lifecycle", nodeName: taskName, phase: "finished", error: errorStr, details: taskDetails });
          let status = describeTaskStatus(taskName, "finished", errorStr);
          if (taskName.trim().toLowerCase() === "select_skills" && activatedSkillNames.length > 0) {
            status = `Context loaded: ${activatedSkillNames.join(", ")}`;
          }
          setStreamingStatus(status);
          return;
        }

        if (eventName === "tool_call") {
          return;
        }

        if (eventName === "tool_result") {
          return;
        }

        if (eventName === "mcp_tool_call") {
          const serverName = String((payload as { server_name?: unknown }).server_name ?? "");
          const toolName = String((payload as { tool_name?: unknown }).tool_name ?? "");
          pushLogEntry({ kind: "mcp_tool_call", serverName, toolName });
          setStreamingStatus(`MCP: ${serverName} \u2192 ${toolName}`);
          return;
        }

        if (eventName === "skills_activated") {
          const p = payload as {
            names?: string[];
            skills?: { name: string; path?: string; description?: string; scope?: string }[];
          };
          const names = p.names ?? [];
          activatedSkillNames = names;
          if (names.length > 0) {
            setStreamingStatus(`Skills loaded: ${names.join(", ")}`);
          }
          return;
        }

        if (eventName === "error") {
          streamErrorMessage = String(
            (payload as { message?: unknown }).message ?? "Unknown stream error"
          );
          setStreamingStatus("Streaming error received");
          return;
        }

        if (eventName !== "done") {
          return;
        }

        // Capture final reasoning text
        if (accumulatedContent.trim()) {
          pushLogEntry({ kind: "reasoning", content: accumulatedContent.trim() });
        }

        didComplete = true;
        const donePayload = payload as {
          session: SessionMetadata;
          user_message: ChatMessage;
          assistant_message: ChatMessage;
        };

        let finalAssistantContent = donePayload.assistant_message.content;
        if (currentPlanItems.length > 0) {
          const { before, after, hasPlan } = splitAtPlan(finalAssistantContent);
          if (hasPlan) {
            finalAssistantContent = [before.trim(), after.trim()]
              .filter((section) => section.length > 0)
              .join("\n\n");
          }
          const persistedPlan = currentPlanItems;
          setMessagePlans((prev) => ({
            ...prev,
            [optimisticAssistantMessage.id]: persistedPlan,
          }));
        }

        setActiveSession((current) =>
          current
            ? {
                session: donePayload.session,
                messages: current.messages.map((message) => {
                  // Keep the optimistic ids so React does not remount the
                  // MessageRow when the server-returned id arrives — the row
                  // should just absorb the final content and artifacts.
                  if (message.id === optimisticUserMessage.id) {
                    return { ...donePayload.user_message, id: message.id };
                  }
                  if (message.id === optimisticAssistantMessage.id) {
                    return {
                      ...donePayload.assistant_message,
                      id: message.id,
                      content: finalAssistantContent,
                    };
                  }
                  return message;
                })
              }
            : current
        );
        setSessions((current) =>
          current
            .map((session) =>
              session.id === donePayload.session.id ? donePayload.session : session
            )
            .sort((left, right) =>
              right.updated_at.localeCompare(left.updated_at)
            )
        );
        setStreaming(null);
      }, abortController.signal);

      if (!didComplete && !abortController.signal.aborted) {
        if (streamErrorMessage) {
          throw new Error(streamErrorMessage);
        }
        throw new Error("The message stream ended before completion.");
      }

      // User-initiated cancel: keep partial response visible, refresh session
      if (abortController.signal.aborted) {
        try {
          const detail = await fetchSession(sessionId);
          setActiveSession((current) => {
            if (!current) return current;
            // Preserve the partial assistant content already shown
            const partialContent = accumulatedContent;
            return {
              session: detail.session,
              messages: current.messages.map((message) => {
                if (message.id === optimisticUserMessage.id) {
                  // Try to find the server-saved user message
                  const serverUser = detail.messages.find((m) => m.role === "user" && m.content === content);
                  return serverUser ? { ...serverUser, id: message.id } : message;
                }
                if (message.id === optimisticAssistantMessage.id) {
                  return { ...message, content: partialContent || message.content };
                }
                return message;
              }),
            };
          });
          setSessions((current) =>
            current
              .map((session) =>
                session.id === detail.session.id ? detail.session : session
              )
              .sort((left, right) =>
                right.updated_at.localeCompare(left.updated_at)
              )
          );
        } catch {
          // Session refresh failed — keep whatever we have
        }
      }
    } catch (caughtError) {
      if (abortController.signal.aborted) {
        // User cancelled — not an error
        return;
      }
      setDraft(content);
      try {
        const detail = await fetchSession(sessionId);
        setActiveSession(detail);
        setSessions((current) =>
          current
            .map((session) =>
              session.id === detail.session.id ? detail.session : session
            )
            .sort((left, right) =>
              right.updated_at.localeCompare(left.updated_at)
            )
        );
      } catch {
        setActiveSession((current) =>
          current
            ? {
                ...current,
                messages: current.messages.filter(
                  (message) =>
                    message.id !== optimisticUserMessage.id &&
                    message.id !== optimisticAssistantMessage.id
                )
              }
            : current
        );
      }
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    } finally {
      streamAbortRef.current = null;
      setStreaming(null);
      setIsSending(false);
    }
  }

  function setStreamingStatus(line: string): void {
    if (!line) {
      return;
    }
    setStreaming((current) =>
      current ? { ...current, statusLine: line } : current
    );
  }

  function handleCancel(): void {
    streamAbortRef.current?.abort();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key !== "Enter") {
      return;
    }

    if (event.shiftKey) {
      return;
    }

    event.preventDefault();
    void handleSend();
  }

  function handleStarterPrompt(prompt: string): void {
    setDraft(prompt);
  }

  function handleToggleSessionMenu(
    event: MouseEvent<HTMLButtonElement>,
    sessionId: string
  ): void {
    event.stopPropagation();
    setOpenSessionMenuId((current) => (current === sessionId ? null : sessionId));
  }

  function handleMenuContainerClick(event: MouseEvent<HTMLDivElement>): void {
    event.stopPropagation();
  }

  function handleRenameInputClick(event: MouseEvent<HTMLInputElement>): void {
    event.stopPropagation();
  }

  function handleRenameInputKeyDown(
    event: KeyboardEvent<HTMLInputElement>,
    session: SessionSummary
  ): void {
    if (event.key === "Enter") {
      event.preventDefault();
      void handleRenameSession(session);
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      handleCancelRenameSession();
    }
  }

  async function createDefaultSession() {
    return createSession(
      undefined,
      modelCatalog?.default_provider,
      modelCatalog?.default_model_name,
      activeSession?.session.database_backend
    );
  }

  function applySessionMetadataUpdate(updatedSession: SessionSummary): void {
    setActiveSession((current) =>
      current && current.session.id === updatedSession.id
        ? {
            ...current,
            session: {
              ...current.session,
              ...updatedSession
            }
          }
        : current
    );
    setSessions((current) =>
      current
        .map((session) =>
          session.id === updatedSession.id ? updatedSession : session
        )
        .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
    );
  }

  const activeProvider = activeSession?.session.model_provider;
  const activeModel = activeSession?.session.model_name;
  const activeProviderModels =
    modelCatalog && activeProvider
      ? getModelsForProvider(modelCatalog.models, activeProvider)
      : [];
  const showComposerStatus = isSending || !!streaming;

  return (
    <div className={isSessionRailCollapsed ? "app-shell session-rail-collapsed" : "app-shell"}>
      <aside className={isSessionRailCollapsed ? "session-rail collapsed" : "session-rail"}>
        <div className="session-rail-top">
          <div className="session-rail-toolbar">
            <div className="brand-lockup">
              <div
                className={
                  isSessionRailCollapsed ? "brand-toggle-stack collapsed" : "brand-toggle-stack"
                }
              >
                <div className="brand-mark">
                  <AppLogo isWorking={isSending || !!streaming} />
                </div>
                {isSessionRailCollapsed ? (
                  <button
                    type="button"
                    className="rail-toggle-button overlay"
                    onClick={handleToggleSessionRail}
                    aria-label="Expand conversations"
                    title="Expand conversations"
                  >
                    <SidebarRailIcon />
                  </button>
                ) : null}
              </div>
            </div>

            {!isSessionRailCollapsed ? (
              <button
                type="button"
                className="rail-toggle-button"
                onClick={handleToggleSessionRail}
                aria-label="Collapse conversations"
                title="Collapse conversations"
              >
                <SidebarRailIcon />
              </button>
            ) : null}
          </div>

          <button className="new-chat-button" onClick={() => void handleNewChat()}>
            {isSessionRailCollapsed ? "+" : "New conversation"}
          </button>
        </div>

        {!isSessionRailCollapsed ? (
          <div className="rail-header">
            <p className="section-label">Conversations</p>
            <span>{sessions.length} total</span>
          </div>
        ) : null}

        {!isSessionRailCollapsed ? (
          <div className="session-list">
            {sessions.map((session) => {
              const isActive = activeSession?.session.id === session.id;

              return (
                <section
                  key={session.id}
                  className={isActive ? "session-tile active" : "session-tile"}
                >
                  <div className="session-tile-row">
                    {editingSessionId === session.id ? (
                    <div className="session-select editing">
                      <div className="session-text">
                        <input
                          ref={renameInputRef}
                          className="session-rename-input"
                          aria-label={`Rename ${session.title}`}
                          value={renameDraft}
                          onChange={(event) => setRenameDraft(event.target.value)}
                          onClick={handleRenameInputClick}
                          onKeyDown={(event) => handleRenameInputKeyDown(event, session)}
                          onBlur={() => void handleRenameSession(session)}
                          disabled={sessionActionId === session.id}
                        />
                        <span className="session-updated">
                          {formatSessionTileTime(session.updated_at)}
                        </span>
                      </div>
                    </div>
                    ) : (
                      <button
                        className="session-select"
                        onClick={() => void handleSelectSession(session.id)}
                      >
                        <div className="session-text">
                          <strong>{session.title}</strong>
                          <span className="session-provider">
                            {databaseLabel(session.database_backend)}
                          </span>
                          <span className="session-updated">
                            {formatSessionTileTime(session.updated_at)}
                          </span>
                        </div>
                      </button>
                    )}

                    <>
                      <button
                        className="session-menu-button"
                        aria-label={`Open actions for ${session.title}`}
                        aria-expanded={openSessionMenuId === session.id}
                        onClick={(event) => handleToggleSessionMenu(event, session.id)}
                        disabled={sessionActionId === session.id || editingSessionId === session.id}
                      >
                        ...
                      </button>

                      {openSessionMenuId === session.id ? (
                        <div className="session-menu" onClick={handleMenuContainerClick}>
                          <button
                            className="session-menu-item"
                            onClick={() => handleStartRenameSession(session)}
                            disabled={sessionActionId === session.id}
                          >
                            <PencilIcon />
                            <span>Rename</span>
                          </button>
                          <div className="session-menu-divider" />
                          <button
                            className="session-menu-item danger"
                            onClick={() => void handleDeleteSession(session)}
                            disabled={sessionActionId === session.id || isSending}
                          >
                            <TrashIcon />
                            <span>Delete</span>
                          </button>
                        </div>
                      ) : null}
                    </>
                  </div>
                </section>
              );
            })}
          </div>
        ) : null}
      </aside>

      <main
        className={isRightPanelOpen ? "chat-panel artifact-panel-open" : "chat-panel"}
        style={
          isRightPanelOpen
            ? ({ "--artifact-panel-width": `${artifactPanelWidth}px` } as CSSProperties)
            : undefined
        }
      >
        <header className="chat-header">
          <div className="chat-header-inner">
            <div className="chat-title-block">
              <h2>{activeSession?.session.title ?? "Loading conversation"}</h2>
            </div>

            {activeSession ? (
              <div className="chat-controls">
                <label className="field-select field-select-database">
                  <span>Data Source</span>
                  <select
                    aria-label="Database backend"
                    value={activeSession.session.database_backend}
                    onChange={(event) =>
                      void handleDatabaseChange(event.target.value as DatabaseBackend)
                    }
                    disabled={isUpdatingDatabase || isUpdatingModel || isSending || activeSession.messages.length > 0}
                  >
                    <option value="sqlite">SQLite</option>
                    <option value="snowflake">Snowflake</option>
                  </select>
                </label>

                <label className="field-select field-select-provider">
                  <span>Provider</span>
                  <select
                    aria-label="Provider"
                    value={activeSession.session.model_provider}
                    onChange={(event) =>
                      void handleProviderChange(event.target.value as ModelProvider)
                    }
                    disabled={
                      isUpdatingDatabase || isUpdatingModel || isSending || !modelCatalog
                    }
                  >
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                  </select>
                </label>

                <label className="field-select field-select-model">
                  <span>Model</span>
                  <select
                    aria-label="Model"
                    value={activeSession.session.model_name}
                    onChange={(event) => void handleModelChange(event.target.value)}
                    disabled={
                      isUpdatingDatabase ||
                      isUpdatingModel ||
                      isSending ||
                      activeProviderModels.length === 0
                    }
                  >
                    {activeProviderModels.map((model) => (
                      <option
                        key={`${model.provider}:${model.model_name}`}
                        value={model.model_name}
                      >
                        {model.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            ) : null}
          </div>
        </header>

        <div className="chat-body">
          <div className="chat-column">
            <section className="chat-feed">
              <div className="chat-feed-inner">
            <div className="sr-only" aria-live="polite">
              {isBootstrapping
                ? "Loading conversations"
                : isSending
                  ? "Assistant is generating a response"
                  : error
                    ? `Error: ${error}`
                    : !activeSession
                      ? "No session selected"
                      : ""}
            </div>

            {isBootstrapping ? (
              <div className="chat-state-card">
                <p className="state-kicker">Initializing</p>
                <h3>Loading conversations and model settings</h3>
              </div>
            ) : null}

            {!isBootstrapping && activeSession && activeSession.messages.length === 0 ? (
              <div className="chat-state-card">
                <p className="state-kicker">Ready</p>
                <h3>A desktop chat layout built for long-running sessions</h3>
                <p>
                  Pick a prior conversation from the left rail or start a new one
                  here. Each session keeps its own model choice, database backend,
                  and message history.
                </p>

                <div className="starter-grid">
                  {starterPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      className="starter-card"
                      onClick={() => handleStarterPrompt(prompt)}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {activeSession ? (
              <MessageList
                messages={activeSession.messages}
                activeArtifactPanelMessageId={rightPanel?.messageId ?? null}
                activeLogPanelMessageId={rightPanel?.mode === "logs" ? rightPanel.messageId : null}
                streamingMessageId={streaming?.assistantMessageId ?? null}
                streamingStatus={streaming?.statusLine ?? ""}
                streamingPlanItems={streaming?.planItems ?? EMPTY_PLAN_ITEMS}
                messagePlans={messagePlans}
                messageLogs={messageLogs}
                onOpenArtifactPanel={handleOpenArtifactPanel}
                onOpenLogPanel={handleOpenLogPanel}
              />
            ) : null}

            <div ref={messagesEndRef} />
              </div>
            </section>

            <footer className="composer-shell">
              <div className="composer-inner">
                {error ? <div className="error-banner">{error}</div> : null}
                {showComposerStatus ? (
                  <div className="composer-status-bar" role="status" aria-live="polite">
                    <span className="composer-status-text">
                      Jeremy is working
                      <span className="composer-status-dots" aria-hidden="true">
                        <span className="composer-status-dot composer-status-dot-1">.</span>
                        <span className="composer-status-dot composer-status-dot-2">.</span>
                        <span className="composer-status-dot composer-status-dot-3">.</span>
                      </span>
                    </span>
                    <button type="button" className="composer-stop-button" onClick={handleCancel}>
                      <StopIcon /> Stop
                    </button>
                  </div>
                ) : null}

                <form className="composer" onSubmit={(event) => void handleSend(event)}>
                  <textarea
                    aria-label="Message Ask Jeremy"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={handleComposerKeyDown}
                    placeholder="Ask Jeremy..."
                    rows={1}
                  />

                  <div className="composer-footer">
                    <div className="composer-hint">Enter to send, Shift+Enter for a new line</div>
                    <button type="submit" disabled={!draft.trim() || isSending || !activeSession}>
                      Send message
                    </button>
                  </div>
                </form>
              </div>
            </footer>
          </div>

          {isRightPanelOpen && activeSession ? (
            <aside
              className="artifact-panel"
              aria-label={rightPanel.mode === "logs" ? "Agent log" : "Artifact viewer"}
            >
              <div
                className="artifact-panel-resizer"
                onMouseDown={handleStartArtifactResize}
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize panel"
              />
              {rightPanel.mode === "artifacts" ? (
                <>
                  <div className="artifact-panel-header">
                    <div>
                      <p className="artifact-panel-kicker">Artifacts</p>
                      <h3>{formatArtifactCount(rightPanel.artifacts.length)}</h3>
                      <p className="artifact-panel-subtitle">
                        Response at {formatTime(rightPanel.messageCreatedAt)}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="artifact-panel-close"
                      onClick={handleCloseRightPanel}
                    >
                      Close
                    </button>
                  </div>

                  <div className="artifact-preview-shell">
                    {rightPanel.artifacts.length > 0 ? (
                      <div className="artifact-preview-stack">
                        {rightPanel.artifacts.map((artifact) => (
                          <section
                            key={artifact.relative_path}
                            className="artifact-preview-card"
                          >
                            <div className="artifact-preview-toolbar">
                              <div className="artifact-preview-title">
                                <strong>{artifact.filename}</strong>
                                <span>{formatArtifactTypeLabel(artifact)}</span>
                              </div>
                              <a
                                className="artifact-preview-link"
                                href={artifactUrl(activeSession.session.id, artifact.relative_path)}
                                target="_blank"
                                rel="noreferrer"
                                title="Open in new tab"
                              >
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg>
                              </a>
                            </div>

                            <div className="artifact-preview-surface">
                              <ArtifactPreview
                                artifact={artifact}
                                sessionId={activeSession.session.id}
                              />
                            </div>
                          </section>
                        ))}
                      </div>
                    ) : (
                      <div className="artifact-preview-empty">Select an artifact to preview.</div>
                    )}
                  </div>
                </>
              ) : (
                <LogPanel
                  messageId={rightPanel.messageId}
                  entries={messageLogs[rightPanel.messageId] ?? []}
                  onClose={handleCloseRightPanel}
                />
              )}
            </aside>
          ) : null}
        </div>
      </main>
    </div>
  );
}

function getModelsForProvider(
  models: ModelCatalogEntry[],
  provider: ModelProvider
): ModelCatalogEntry[] {
  return models.filter((model) => model.provider === provider);
}

function describeTaskStatus(
  taskName: string,
  phase: "started" | "finished",
  errorMessage: string | null = null
): string {
  const normalized = taskName.trim().toLowerCase();

  if (errorMessage) {
    return `Task failed: ${taskName}`;
  }

  if (normalized === "select_skills") {
    return phase === "started" ? "Reviewing context" : "Context review complete";
  }

  if (normalized === "tools") {
    return phase === "started" ? "Running tools" : "Tool work complete";
  }

  if (normalized === "call_model") {
    return phase === "started" ? "Drafting response" : "Draft ready";
  }

  if (normalized === "compact_messages") {
    return phase === "started"
      ? "Summarizing earlier messages"
      : "Summary complete";
  }

  return phase === "started"
    ? `Running ${taskName || "task"}`
    : `${taskName || "Task"} complete`;
}

function formatArtifactCount(count: number): string {
  return count === 1 ? "1 output" : `${count} outputs`;
}

function formatArtifactTypeLabel(artifact: ChatArtifact): string {
  const extension = artifactExtension(artifact);
  if (extension === "sql") {
    return "sql";
  }
  if (extension === "py") {
    return "python";
  }
  const mediaType = artifact.mime_type?.toLowerCase() ?? "";
  if (mediaType.startsWith("image/")) {
    return "image";
  }
  if (mediaType === "application/pdf") {
    return "pdf";
  }
  if (mediaType.includes("json")) {
    return "json";
  }
  if (mediaType.includes("csv")) {
    return "csv";
  }
  if (mediaType.startsWith("text/html")) {
    return "html";
  }
  if (mediaType.startsWith("text/")) {
    return "text";
  }
  return extension ?? "file";
}

function artifactExtension(artifact: ChatArtifact): string | null {
  const parts = artifact.filename.split(".");
  if (parts.length < 2) {
    return null;
  }
  return parts.pop()?.toLowerCase() ?? null;
}

function isCodeArtifact(artifact: ChatArtifact): boolean {
  const extension = artifactExtension(artifact);
  if (extension === "sql" || extension === "py") {
    return true;
  }
  const mediaType = artifact.mime_type?.toLowerCase() ?? "";
  return (
    mediaType === "application/sql" ||
    mediaType === "application/x-python" ||
    mediaType === "text/x-python" ||
    mediaType === "text/x-sql"
  );
}

function codeLanguageFromArtifact(artifact: ChatArtifact): string {
  const extension = artifactExtension(artifact);
  if (extension === "py") {
    return "python";
  }
  if (extension === "sql") {
    return "sql";
  }
  return "text";
}

function clampArtifactPanelWidth(width: number): number {
  return Math.min(MAX_ARTIFACT_PANEL_WIDTH, Math.max(MIN_ARTIFACT_PANEL_WIDTH, width));
}

function normalizePlanKey(action: string): string {
  return action
    .toLowerCase()
    .replace(/\*+/g, "")
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function progressStatus(
  previous: PlanItemStatus,
  next: PlanItemStatus
): PlanItemStatus {
  const previousRank = STATUS_ORDER.indexOf(previous);
  const nextRank = STATUS_ORDER.indexOf(next);
  if (nextRank < 0) {
    return previous;
  }
  if (previousRank < 0) {
    return next;
  }
  return nextRank >= previousRank ? next : previous;
}

function parsePlanItemsFromContent(content: string): PlanItem[] {
  const lines = content.split(/\r?\n/);
  const items: PlanItem[] = [];
  let inPlanSection = false;
  let sawItem = false;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];

    if (!inPlanSection) {
      if (PLAN_HEADER_PATTERN.test(line)) {
        inPlanSection = true;
        sawItem = false;
      }
      continue;
    }

    if (line.trim() === "") {
      if (sawItem) {
        const hasMoreItems = lines
          .slice(index + 1)
          .some((future) => PLAN_ITEM_PATTERN.test(future));
        if (!hasMoreItems) {
          break;
        }
      }
      continue;
    }

    const match = PLAN_ITEM_PATTERN.exec(line);
    if (!match) {
      if (sawItem) {
        break;
      }
      continue;
    }

    const action = match[1].replace(/\*+/g, "").trim();
    const status = match[2].toLowerCase() as PlanItemStatus;
    items.push({
      key: normalizePlanKey(action),
      action,
      status,
    });
    sawItem = true;
  }

  return items;
}

function mergePlans(previous: PlanItem[], current: PlanItem[]): PlanItem[] {
  if (current.length === 0) {
    return previous;
  }

  const previousByKey = new Map<string, PlanItem>();
  for (const item of previous) {
    if (item.key) {
      previousByKey.set(item.key, item);
    }
  }

  const merged: PlanItem[] = [];
  const absorbedKeys = new Set<string>();

  current.forEach((item, index) => {
    const existing =
      (item.key && previousByKey.get(item.key)) ||
      (!absorbedKeys.has(previous[index]?.key ?? "") ? previous[index] : undefined);

    if (existing) {
      absorbedKeys.add(existing.key);
      merged.push({
        key: existing.key || item.key,
        action: item.action || existing.action,
        status: progressStatus(existing.status, item.status),
      });
    } else {
      merged.push(item);
      if (item.key) {
        absorbedKeys.add(item.key);
      }
    }
  });

  for (const item of previous) {
    if (!absorbedKeys.has(item.key)) {
      merged.push(item);
      absorbedKeys.add(item.key);
    }
  }

  return merged;
}

function splitAtPlan(content: string): {
  before: string;
  after: string;
  hasPlan: boolean;
} {
  const lines = content.split(/\r?\n/);
  let headerIndex = -1;
  for (let index = 0; index < lines.length; index += 1) {
    if (PLAN_HEADER_PATTERN.test(lines[index])) {
      headerIndex = index;
      break;
    }
  }
  if (headerIndex < 0) {
    return { before: content, after: "", hasPlan: false };
  }

  let lastItemIndex = headerIndex;
  for (let index = headerIndex + 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.trim() === "") {
      continue;
    }
    if (PLAN_ITEM_PATTERN.test(line)) {
      lastItemIndex = index;
      continue;
    }
    break;
  }

  const before = lines.slice(0, headerIndex).join("\n");
  const after = lines.slice(lastItemIndex + 1).join("\n");
  return { before, after, hasPlan: true };
}

function isEmbeddableArtifact(artifact: ChatArtifact): boolean {
  const mediaType = artifact.mime_type?.toLowerCase() ?? "";
  return (
    mediaType.startsWith("image/") ||
    mediaType.startsWith("text/") ||
    mediaType === "application/pdf" ||
    mediaType === "application/json"
  );
}

function CodeBlockWithCopy({ children, ...rest }: ComponentPropsWithoutRef<"pre">): ReactNode {
  const [copied, setCopied] = useState(false);
  const preRef = useRef<HTMLPreElement>(null);

  function handleCopy() {
    const text = preRef.current?.innerText ?? "";
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <div className="code-block-wrapper">
      <button
        type="button"
        className={`code-copy-btn${copied ? " copied" : ""}`}
        onClick={handleCopy}
        aria-label="Copy code"
        title="Copy code"
      >
        {copied ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
        )}
      </button>
      <pre ref={preRef} {...rest}>{children}</pre>
    </div>
  );
}

const MarkdownContent = memo(function MarkdownContent({ content }: { content: string }): ReactNode {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: (props: ComponentPropsWithoutRef<"a">) => (
          <a {...props} target="_blank" rel="noreferrer" />
        ),
        pre: (props: ComponentPropsWithoutRef<"pre">) => (
          <CodeBlockWithCopy {...props} />
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
});

function ArtifactPreview({
  artifact,
  sessionId,
}: {
  artifact: ChatArtifact;
  sessionId: string;
}): ReactNode {
  const previewUrl = artifactUrl(sessionId, artifact.relative_path);

  if (isCodeArtifact(artifact)) {
    return (
      <CodeArtifactPreview
        url={previewUrl}
        filename={artifact.filename}
        language={codeLanguageFromArtifact(artifact)}
      />
    );
  }

  if (artifact.mime_type?.startsWith("image/")) {
    return <img className="artifact-preview-image" src={previewUrl} alt={artifact.filename} />;
  }

  if (isEmbeddableArtifact(artifact)) {
    return (
      <iframe
        className="artifact-preview-frame"
        src={previewUrl}
        title={artifact.filename}
      />
    );
  }

  return (
    <div className="artifact-preview-empty">
      <span>Preview is not available for this file type.</span>
      <a href={previewUrl} target="_blank" rel="noreferrer" title="Open in new tab">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg>
      </a>
    </div>
  );
}

function ArtifactCopyButton({ text }: { text: string }): ReactNode {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <button
      type="button"
      className={`artifact-code-copy-btn${copied ? " copied" : ""}`}
      onClick={handleCopy}
      aria-label="Copy code"
      title="Copy code"
    >
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
      )}
    </button>
  );
}

function CodeArtifactPreview({
  url,
  filename,
  language,
}: {
  url: string;
  filename: string;
  language: string;
}): ReactNode {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "ready"; text: string }
    | { status: "error"; message: string }
  >({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetch(url)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Failed to load code (${response.status})`);
        }
        return response.text();
      })
      .then((text) => {
        if (!cancelled) {
          setState({ status: "ready", text });
        }
      })
      .catch((caughtError) => {
        if (!cancelled) {
          setState({
            status: "error",
            message:
              caughtError instanceof Error
                ? caughtError.message
                : "Unknown error",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [url]);

  if (state.status === "loading") {
    return (
      <div className="artifact-code-block">
        <div className="artifact-code-header">
          <span className="artifact-code-language">{language}</span>
          <span className="artifact-code-filename">{filename}</span>
        </div>
        <div className="artifact-preview-empty">Loading code…</div>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="artifact-code-block">
        <div className="artifact-code-header">
          <span className="artifact-code-language">{language}</span>
          <span className="artifact-code-filename">{filename}</span>
        </div>
        <div className="artifact-preview-empty">
          <span>Could not load code: {state.message}</span>
          <a href={url} target="_blank" rel="noreferrer" title="Open in new tab">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg>
          </a>
        </div>
      </div>
    );
  }

  const lines = state.text.split(/\r?\n/);
  return (
    <div className="artifact-code-block">
      <div className="artifact-code-header">
        <span className="artifact-code-language">{language}</span>
        <span className="artifact-code-filename">{filename}</span>
        <ArtifactCopyButton text={state.text} />
      </div>
      <pre className={`artifact-code-pre language-${language}`}>
        <code>
          {lines.map((line, index) => (
            <span key={index} className="artifact-code-line">
              <span className="artifact-code-line-number">{index + 1}</span>
              <span className="artifact-code-line-text">{line || " "}</span>
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}

const StreamingPlan = memo(function StreamingPlan({
  items,
}: {
  items: PlanItem[];
}): ReactNode {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="stream-plan-block">
      <div className="stream-plan-title">Plan</div>
      <ul className="stream-plan-list">
        {items.map((item, index) => {
          const statusClass = `stream-plan-item-${item.status.replace(/\s+/g, "-")}`;
          return (
            <li
              key={item.key || `${index}:${item.action}`}
              className={`stream-plan-item ${statusClass}`}
            >
              <span className="stream-plan-action">{item.action}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
});

function AssistantContent({
  content,
  planItems,
}: {
  content: string;
  planItems: PlanItem[];
}): ReactNode {
  if (planItems.length === 0) {
    return content ? (
      <div className="message-copy markdown-content">
        <MarkdownContent content={content} />
      </div>
    ) : null;
  }

  const { before, after, hasPlan } = splitAtPlan(content);
  const beforeContent = hasPlan ? before : "";
  const afterContent = hasPlan ? after : content;

  return (
    <>
      {beforeContent.trim() ? (
        <div className="message-copy markdown-content">
          <MarkdownContent content={beforeContent} />
        </div>
      ) : null}
      <StreamingPlan items={planItems} />
      {afterContent.trim() ? (
        <div className="message-copy markdown-content">
          <MarkdownContent content={afterContent} />
        </div>
      ) : null}
    </>
  );
}

const MessageRow = memo(function MessageRow({
  message,
  isArtifactPanelMessage,
  isStreaming,
  streamingStatus,
  planItems,
  hasLogs,
  isLogPanelMessage,
  onOpenArtifactPanel,
  onOpenLogPanel,
}: {
  message: ChatMessage;
  isArtifactPanelMessage: boolean;
  isStreaming: boolean;
  streamingStatus: string;
  planItems: PlanItem[];
  hasLogs: boolean;
  isLogPanelMessage: boolean;
  onOpenArtifactPanel: (message: ChatMessage) => void;
  onOpenLogPanel: (messageId: string) => void;
}): ReactNode {
  const isAssistant = message.role === "assistant";
  const rowClassName = isAssistant
    ? isStreaming
      ? "message-row assistant pending"
      : "message-row assistant"
    : "message-row user";

  return (
    <article className={rowClassName}>
      {isAssistant ? (
        <div className="message-avatar">
          <AssistantAvatarIcon />
        </div>
      ) : null}

      <div className="message-card">
        <div className="message-meta">
          <span>{messageAuthorLabel(message.role)}</span>
          <span>{isStreaming ? "working" : formatTime(message.created_at)}</span>
        </div>
        {isStreaming && streamingStatus ? (
          <div className="stream-status-line">{streamingStatus}</div>
        ) : null}
        {isAssistant ? (
          <AssistantContent content={message.content} planItems={planItems} />
        ) : (
          <div className="message-copy plain-text">{message.content}</div>
        )}
        {isAssistant && message.artifacts.length > 0 ? (
          <div className="message-artifact-summary">
            <div className="message-artifact-summary-copy">
              <span className="message-artifact-summary-count">
                {formatArtifactCount(message.artifacts.length)}
              </span>
              <div className="message-artifact-summary-list">
                {message.artifacts.map((artifact) => (
                  <span
                    key={`${message.id}:${artifact.relative_path}`}
                    className="message-artifact-chip"
                  >
                    {artifact.filename}
                  </span>
                ))}
              </div>
            </div>
            <button
              type="button"
              className={
                isArtifactPanelMessage
                  ? "message-artifact-preview-button active"
                  : "message-artifact-preview-button"
              }
              onClick={() => onOpenArtifactPanel(message)}
              title="Preview"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="18" rx="2" /><line x1="10" y1="3" x2="10" y2="21" /></svg>
            </button>
          </div>
        ) : null}
        {isAssistant && hasLogs ? (
          <div className="message-log-action">
            <button
              type="button"
              className={isLogPanelMessage ? "message-log-button active" : "message-log-button"}
              onClick={() => onOpenLogPanel(message.id)}
            >
              <LogIcon /> <span>Log</span>
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
});

const MessageList = memo(function MessageList({
  messages,
  activeArtifactPanelMessageId,
  activeLogPanelMessageId,
  streamingMessageId,
  streamingStatus,
  streamingPlanItems,
  messagePlans,
  messageLogs,
  onOpenArtifactPanel,
  onOpenLogPanel,
}: {
  messages: ChatMessage[];
  activeArtifactPanelMessageId: string | null;
  activeLogPanelMessageId: string | null;
  streamingMessageId: string | null;
  streamingStatus: string;
  streamingPlanItems: PlanItem[];
  messagePlans: Record<string, PlanItem[]>;
  messageLogs: Record<string, LogEntry[]>;
  onOpenArtifactPanel: (message: ChatMessage) => void;
  onOpenLogPanel: (messageId: string) => void;
}): ReactNode {
  return (
    <>
      {messages.map((message) => {
        const isStreaming = message.id === streamingMessageId;
        const planItems = isStreaming
          ? streamingPlanItems
          : messagePlans[message.id] ?? EMPTY_PLAN_ITEMS;
        const logEntries = messageLogs[message.id];
        return (
          <MessageRow
            key={message.id}
            message={message}
            isArtifactPanelMessage={activeArtifactPanelMessageId === message.id}
            isStreaming={isStreaming}
            streamingStatus={isStreaming ? streamingStatus : ""}
            planItems={planItems}
            hasLogs={logEntries != null && logEntries.length > 0}
            isLogPanelMessage={activeLogPanelMessageId === message.id}
            onOpenArtifactPanel={onOpenArtifactPanel}
            onOpenLogPanel={onOpenLogPanel}
          />
        );
      })}
    </>
  );
});

function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="14" height="14">
      <rect
        x="6" y="6" width="12" height="12" rx="2"
        fill="currentColor"
      />
    </svg>
  );
}

function LogIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="14" height="14">
      <path
        d="M4 6h16M4 12h16M4 18h10"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function formatLogTime(timestamp: number): string {
  const d = new Date(timestamp);
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
}

function ToolResultDetails({ details }: { details: Record<string, unknown> }): ReactNode {
  if (Object.keys(details).length === 0) {
    return null;
  }

  const parts: ReactNode[] = [];

  // SQL query results
  if ("row_count" in details) {
    const cols = Array.isArray(details.columns) ? (details.columns as string[]) : [];
    parts.push(
      <div key="sql" className="log-entry-detail-section">
        <div className="log-entry-detail-row">
          <span className="log-entry-detail-label">Database</span>
          <span>{String(details.database ?? "")}</span>
        </div>
        <div className="log-entry-detail-row">
          <span className="log-entry-detail-label">Rows</span>
          <span>{String(details.row_count)}{details.truncated ? " (truncated)" : ""}</span>
        </div>
        {cols.length > 0 ? (
          <div className="log-entry-detail-row">
            <span className="log-entry-detail-label">Columns</span>
            <span className="log-entry-detail-columns">{cols.join(", ")}</span>
          </div>
        ) : null}
      </div>
    );
  }

  // Analysis summary
  if ("summary" in details) {
    parts.push(
      <div key="summary" className="log-entry-detail-section">
        <span className="log-entry-detail-label">Summary</span>
        <CodeBlockWithCopy className="log-entry-code">{String(details.summary)}</CodeBlockWithCopy>
      </div>
    );
  }

  // Analysis metrics
  if ("metrics" in details && typeof details.metrics === "object" && details.metrics !== null) {
    const metrics = details.metrics as Record<string, unknown>;
    const metricEntries = Object.entries(metrics);
    if (metricEntries.length > 0) {
      parts.push(
        <div key="metrics" className="log-entry-detail-section">
          <span className="log-entry-detail-label">Metrics</span>
          <div className="log-entry-metrics-grid">
            {metricEntries.map(([key, value]) => (
              <div key={key} className="log-entry-detail-row">
                <span className="log-entry-detail-metric-key">{key}</span>
                <span>{String(value)}</span>
              </div>
            ))}
          </div>
        </div>
      );
    }
  }

  // Table info
  if ("table_rows" in details) {
    parts.push(
      <div key="table" className="log-entry-detail-row">
        <span className="log-entry-detail-label">Table output</span>
        <span>{String(details.table_rows)} rows</span>
      </div>
    );
  }

  // Findings count
  if ("findings_count" in details) {
    parts.push(
      <div key="findings" className="log-entry-detail-row">
        <span className="log-entry-detail-label">Findings</span>
        <span>{String(details.findings_count)}</span>
      </div>
    );
  }

  // Stdout / stderr (shell, python)
  if ("stdout" in details && String(details.stdout).trim()) {
    parts.push(
      <div key="stdout" className="log-entry-detail-section">
        <span className="log-entry-detail-label">stdout</span>
        <CodeBlockWithCopy className="log-entry-code">{String(details.stdout)}</CodeBlockWithCopy>
      </div>
    );
  }
  if ("stderr" in details && String(details.stderr).trim()) {
    parts.push(
      <div key="stderr" className="log-entry-detail-section">
        <span className="log-entry-detail-label">stderr</span>
        <CodeBlockWithCopy className="log-entry-code log-entry-stderr">{String(details.stderr)}</CodeBlockWithCopy>
      </div>
    );
  }

  // Artifacts produced
  if ("artifacts_count" in details && Number(details.artifacts_count) > 0) {
    parts.push(
      <div key="artifacts" className="log-entry-detail-row">
        <span className="log-entry-detail-label">Artifacts produced</span>
        <span>{String(details.artifacts_count)}</span>
      </div>
    );
  }

  // Error message (fallback for errors)
  if ("message" in details && String(details.message).trim()) {
    parts.push(
      <div key="message" className="log-entry-detail-section">
        <span className="log-entry-detail-label">Message</span>
        <CodeBlockWithCopy className="log-entry-code">{String(details.message)}</CodeBlockWithCopy>
      </div>
    );
  }

  // Raw fallback
  if ("raw" in details) {
    parts.push(
      <div key="raw" className="log-entry-detail-section">
        <CodeBlockWithCopy className="log-entry-code">{String(details.raw)}</CodeBlockWithCopy>
      </div>
    );
  }

  if (parts.length === 0) {
    return null;
  }

  return <div className="log-entry-details">{parts}</div>;
}

function LogEntryCard({ entry }: { entry: LogEntry }): ReactNode {
  const time = formatLogTime(entry.timestamp);

  if (entry.kind === "reasoning") {
    return (
      <div className="log-entry log-entry-reasoning">
        <div className="log-entry-header">
          <span className="log-entry-kind">reasoning</span>
          <span className="log-entry-time">{time}</span>
        </div>
        <CodeBlockWithCopy className="log-entry-code">{entry.content}</CodeBlockWithCopy>
      </div>
    );
  }

  if (entry.kind === "node_lifecycle") {
    // Error entries
    if (entry.error) {
      return (
        <div className="log-entry log-entry-node log-entry-error">
          <div className="log-entry-header">
            <span className="log-entry-kind">{entry.nodeName} failed</span>
            <span className="log-entry-time">{time}</span>
          </div>
          <CodeBlockWithCopy className="log-entry-code">{entry.error}</CodeBlockWithCopy>
        </div>
      );
    }

    // "finished" entries — render as full cards with details
    const d = entry.details;
    const hasDetails = Object.keys(d).length > 0;

    // select_skills finished
    if (entry.nodeName === "select_skills") {
      const skills = Array.isArray(d.skills) ? (d.skills as { name: string; path?: string; description?: string; scope?: string }[]) : [];
      const skillNames = Array.isArray(d.skill_names) ? (d.skill_names as string[]) : [];
      if (skills.length > 0) {
        return (
          <div className="log-entry log-entry-skills">
            <div className="log-entry-header">
              <span className="log-entry-kind">select_skills {"\u2714"}</span>
              <span className="log-entry-time">{time}</span>
            </div>
            <div className="log-entry-skill-list">
              {skills.map((skill) => (
                <div key={skill.name} className="log-entry-skill-item">
                  <div className="log-entry-skill-name-row">
                    <span className="log-entry-chip">{skill.name}</span>
                    {skill.scope ? <span className="log-entry-skill-scope">{skill.scope}</span> : null}
                  </div>
                  {skill.description ? (
                    <span className="log-entry-skill-desc">{skill.description}</span>
                  ) : null}
                  {skill.path ? (
                    <span className="log-entry-skill-path">{skill.path}</span>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        );
      }
      if (skillNames.length > 0) {
        return (
          <div className="log-entry log-entry-skills">
            <div className="log-entry-header">
              <span className="log-entry-kind">select_skills {"\u2714"}</span>
              <span className="log-entry-time">{time}</span>
            </div>
            <div className="log-entry-chip-list">
              {skillNames.map((name) => (
                <span key={name} className="log-entry-chip">{name}</span>
              ))}
            </div>
          </div>
        );
      }
      // No skills activated
      return (
        <div className="log-entry log-entry-node">
          <div className="log-entry-header">
            <span className="log-entry-kind">select_skills {"\u2714"}</span>
            <span className="log-entry-time">{time}</span>
          </div>
          <span className="log-entry-detail-muted">No skills activated</span>
        </div>
      );
    }

    // call_model finished
    if (entry.nodeName === "call_model") {
      const toolCalls = Array.isArray(d.tool_calls) ? (d.tool_calls as { tool_name: string; tool_args: Record<string, unknown> }[]) : [];
      if (toolCalls.length > 0) {
        return (
          <div className="log-entry log-entry-tool-call">
            <div className="log-entry-header">
              <span className="log-entry-kind">call_model {"\u2714"}</span>
              <span className="log-entry-time">{time}</span>
            </div>
            <span className="log-entry-detail-muted">Tool calls: {toolCalls.length}</span>
            {toolCalls.map((tc, i) => {
              const specialKeys = ["query", "script", "command", "sql_query"];
              const specialKey = specialKeys.find((k) => k in tc.tool_args);
              return (
                <div key={i} className="log-entry-detail-section">
                  <strong className="log-entry-tool-name">{tc.tool_name}</strong>
                  {specialKey ? (
                    <CodeBlockWithCopy className="log-entry-code">{String(tc.tool_args[specialKey])}</CodeBlockWithCopy>
                  ) : (
                    <CodeBlockWithCopy className="log-entry-code">{JSON.stringify(tc.tool_args, null, 2)}</CodeBlockWithCopy>
                  )}
                </div>
              );
            })}
          </div>
        );
      }
      return (
        <div className="log-entry log-entry-node">
          <div className="log-entry-header">
            <span className="log-entry-kind">call_model {"\u2714"}</span>
            <span className="log-entry-time">{time}</span>
          </div>
          <span className="log-entry-detail-muted">Generated response (no tool calls)</span>
        </div>
      );
    }

    // tools finished
    if (entry.nodeName === "tools") {
      const toolResults = Array.isArray(d.tool_results) ? (d.tool_results as { tool_name: string; ok: boolean | null; details: Record<string, unknown> }[]) : [];
      if (toolResults.length > 0) {
        return (
          <div className="log-entry log-entry-tool-result">
            <div className="log-entry-header">
              <span className="log-entry-kind">tools {"\u2714"}</span>
              <span className="log-entry-time">{time}</span>
            </div>
            {toolResults.map((tr, i) => {
              const isError = tr.ok === false;
              return (
                <div key={i} className="log-entry-detail-section">
                  <div className="log-entry-status-row">
                    <strong className="log-entry-tool-name">{tr.tool_name}</strong>
                    <span className={isError ? "log-entry-status-badge error" : "log-entry-status-badge ok"}>
                      {isError ? "FAILED" : "OK"}
                    </span>
                  </div>
                  <ToolResultDetails details={tr.details} />
                </div>
              );
            })}
          </div>
        );
      }
    }

    // Default finished: compact with no details
    if (!hasDetails) {
      return null;
    }

    // Generic finished with unknown details
    return (
      <div className="log-entry log-entry-node">
        <div className="log-entry-header">
          <span className="log-entry-kind">{entry.nodeName} {"\u2714"}</span>
          <span className="log-entry-time">{time}</span>
        </div>
        <CodeBlockWithCopy className="log-entry-code">{JSON.stringify(d, null, 2)}</CodeBlockWithCopy>
      </div>
    );
  }

  if (entry.kind === "mcp_tool_call") {
    return (
      <div className="log-entry log-entry-mcp">
        <div className="log-entry-header">
          <span className="log-entry-kind">mcp</span>
          <span className="log-entry-time">{time}</span>
        </div>
        <span>{entry.serverName} &rarr; {entry.toolName}</span>
      </div>
    );
  }

  return null;
}

type LogStep =
  | { type: "skills"; finishedEntry: LogEntry }
  | { type: "iteration"; index: number; callModelFinished: LogEntry | null; toolsFinished: LogEntry | null; reasoningEntries: LogEntry[]; mcpEntries: LogEntry[] }
  | { type: "orphan"; entry: LogEntry };

const NOISE_NODES = new Set(["compact_messages", "enforce_analysis"]);

function groupLogEntries(entries: LogEntry[]): LogStep[] {
  const steps: LogStep[] = [];
  let iterationIndex = 0;
  let currentIteration: { type: "iteration"; index: number; callModelFinished: LogEntry | null; toolsFinished: LogEntry | null; reasoningEntries: LogEntry[]; mcpEntries: LogEntry[] } | null = null;

  function flushIteration(): void {
    if (currentIteration) {
      steps.push(currentIteration);
      currentIteration = null;
    }
  }

  for (const entry of entries) {
    if (entry.kind === "node_lifecycle") {
      // Skip started phases entirely
      if (entry.phase === "started") continue;
      // Skip noise nodes
      if (NOISE_NODES.has(entry.nodeName)) continue;

      if (entry.nodeName === "select_skills") {
        flushIteration();
        steps.push({ type: "skills", finishedEntry: entry });
        continue;
      }

      if (entry.nodeName === "call_model") {
        flushIteration();
        iterationIndex += 1;
        currentIteration = { type: "iteration", index: iterationIndex, callModelFinished: entry, toolsFinished: null, reasoningEntries: [], mcpEntries: [] };
        continue;
      }

      if (entry.nodeName === "tools") {
        if (currentIteration) {
          currentIteration.toolsFinished = entry;
        } else {
          // tools without a preceding call_model — wrap in its own iteration
          iterationIndex += 1;
          steps.push({ type: "iteration", index: iterationIndex, callModelFinished: null, toolsFinished: entry, reasoningEntries: [], mcpEntries: [] });
        }
        continue;
      }

      // Other node_lifecycle finished entries (not noise)
      flushIteration();
      steps.push({ type: "orphan", entry });
      continue;
    }

    if (entry.kind === "reasoning") {
      if (currentIteration) {
        currentIteration.reasoningEntries.push(entry);
      } else {
        // Reasoning before any iteration — start a new one
        iterationIndex += 1;
        currentIteration = { type: "iteration", index: iterationIndex, callModelFinished: null, toolsFinished: null, reasoningEntries: [entry], mcpEntries: [] };
      }
      continue;
    }

    if (entry.kind === "mcp_tool_call") {
      if (currentIteration) {
        currentIteration.mcpEntries.push(entry);
      } else {
        iterationIndex += 1;
        currentIteration = { type: "iteration", index: iterationIndex, callModelFinished: null, toolsFinished: null, reasoningEntries: [], mcpEntries: [entry] };
      }
      continue;
    }

    // Fallback
    flushIteration();
    steps.push({ type: "orphan", entry });
  }

  flushIteration();
  return steps;
}

function iterationToolNames(step: LogStep & { type: "iteration" }): string[] {
  if (!step.callModelFinished || step.callModelFinished.kind !== "node_lifecycle") return [];
  const d = step.callModelFinished.details;
  const toolCalls = Array.isArray(d.tool_calls) ? (d.tool_calls as { tool_name: string }[]) : [];
  return toolCalls.map((tc) => tc.tool_name);
}

function iterationHasError(step: LogStep & { type: "iteration" }): boolean {
  if (step.callModelFinished?.kind === "node_lifecycle" && step.callModelFinished.error) return true;
  if (step.toolsFinished?.kind === "node_lifecycle" && step.toolsFinished.error) return true;
  if (step.toolsFinished?.kind === "node_lifecycle") {
    const d = step.toolsFinished.details;
    const toolResults = Array.isArray(d.tool_results) ? (d.tool_results as { ok: boolean | null }[]) : [];
    if (toolResults.some((tr) => tr.ok === false)) return true;
  }
  return false;
}

function skillStepLabel(step: LogStep & { type: "skills" }): string {
  const entry = step.finishedEntry;
  if (entry.kind !== "node_lifecycle") return "Skills";
  const d = entry.details;
  const skills = Array.isArray(d.skills) ? (d.skills as { name: string }[]) : [];
  if (skills.length > 0) return `Skills: ${skills.map((s) => s.name).join(", ")}`;
  const skillNames = Array.isArray(d.skill_names) ? (d.skill_names as string[]) : [];
  if (skillNames.length > 0) return `Skills: ${skillNames.join(", ")}`;
  return "Skills: none";
}

function LogStepSection({ step, defaultOpen }: { step: LogStep; defaultOpen: boolean }): ReactNode {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  if (step.type === "orphan") {
    return <LogEntryCard entry={step.entry} />;
  }

  if (step.type === "skills") {
    const label = skillStepLabel(step);
    const hasError = step.finishedEntry.kind === "node_lifecycle" && !!step.finishedEntry.error;
    return (
      <details
        className={`log-step log-step-skills${hasError ? " log-step-error" : ""}`}
        open={isOpen || hasError || undefined}
        onToggle={(e) => setIsOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary className="log-step-summary">
          <span className="log-step-icon">{"\u2728"}</span>
          <span className="log-step-label">{label}</span>
        </summary>
        <div className="log-step-content">
          <LogEntryCard entry={step.finishedEntry} />
        </div>
      </details>
    );
  }

  // iteration
  const toolNames = iterationToolNames(step);
  const hasError = iterationHasError(step);
  const toolSummary = toolNames.length > 0 ? toolNames.join(", ") : "response";
  const statusBadge = hasError ? "ERR" : "OK";
  const label = `Iteration ${step.index} \u2014 ${toolSummary}`;

  return (
    <details
      className={`log-step log-step-iteration${hasError ? " log-step-error" : ""}`}
      open={isOpen || hasError || undefined}
      onToggle={(e) => setIsOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary className="log-step-summary">
        <span className="log-step-icon">{hasError ? "\u2717" : "\u2714"}</span>
        <span className="log-step-label">{label}</span>
        <span className={hasError ? "log-entry-status-badge error" : "log-entry-status-badge ok"}>{statusBadge}</span>
      </summary>
      <div className="log-step-content">
        {step.reasoningEntries.map((e) => (
          <LogEntryCard key={e.id} entry={e} />
        ))}
        {step.mcpEntries.map((e) => (
          <LogEntryCard key={e.id} entry={e} />
        ))}
        {step.callModelFinished ? <LogEntryCard entry={step.callModelFinished} /> : null}
        {step.toolsFinished ? <LogEntryCard entry={step.toolsFinished} /> : null}
      </div>
    </details>
  );
}

function LogPanel({
  messageId,
  entries,
  onClose,
}: {
  messageId: string;
  entries: LogEntry[];
  onClose: () => void;
}): ReactNode {
  const steps = groupLogEntries(entries);
  const stepCount = steps.length;

  return (
    <>
      <div className="artifact-panel-header">
        <div>
          <p className="artifact-panel-kicker">Agent Log</p>
          <h3>{stepCount === 1 ? "1 step" : `${stepCount} steps`}</h3>
        </div>
        <button type="button" className="artifact-panel-close" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="log-panel-scroll">
        <div className="log-entry-stack">
          {steps.map((step, i) => {
            const key = step.type === "orphan" ? step.entry.id : `step-${i}`;
            const isLast = i === steps.length - 1;
            return <LogStepSection key={key} step={step} defaultOpen={isLast} />;
          })}
        </div>
      </div>
    </>
  );
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M4 20l3.5-.8L18 8.7 15.3 6 4.8 16.5 4 20zm11.3-15.4L18 7.3"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M5 7h14m-9-3h4m-7 3 1 12h8l1-12M10 10v6m4-6v6"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function SidebarRailIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect
        x="3.5"
        y="4"
        width="17"
        height="16"
        rx="4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="M10.5 5v14"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function AppLogo({ isWorking }: { isWorking: boolean }) {
  const [eyeOffset, setEyeOffset] = useState({ x: 0, y: 0 });
  const [expression, setExpression] = useState<
    "neutral" | "blink" | "dots" | "chevrons" | "wink" | "smile" | "working"
  >("neutral");
  const [workingFrame, setWorkingFrame] = useState(0);

  useEffect(() => {
    let frameId = 0;

    if (isWorking) {
      setEyeOffset({ x: 0, y: 0 });
      return () => {
        cancelAnimationFrame(frameId);
      };
    }

    function updateEyeOffset(clientX: number, clientY: number): void {
      const normalizedX = window.innerWidth > 0 ? clientX / window.innerWidth - 0.5 : 0;
      const normalizedY = window.innerHeight > 0 ? clientY / window.innerHeight - 0.5 : 0;
      const nextOffset = {
        x: Math.max(-1, Math.min(1, normalizedX * 2)) * 2.8,
        y: Math.max(-1, Math.min(1, normalizedY * 2)) * 2,
      };

      cancelAnimationFrame(frameId);
      frameId = window.requestAnimationFrame(() => {
        setEyeOffset(nextOffset);
      });
    }

    function handlePointerMove(event: PointerEvent): void {
      updateEyeOffset(event.clientX, event.clientY);
    }

    function handlePointerLeave(): void {
      cancelAnimationFrame(frameId);
      frameId = window.requestAnimationFrame(() => {
        setEyeOffset({ x: 0, y: 0 });
      });
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerleave", handlePointerLeave);
    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerleave", handlePointerLeave);
    };
  }, [isWorking]);

  useEffect(() => {
    let nextExpressionTimeout = 0;
    let resetExpressionTimeout = 0;
    const expressions = ["blink", "dots", "chevrons", "wink", "smile"] as const;

    if (isWorking) {
      setExpression("working");
      return () => {
        window.clearTimeout(nextExpressionTimeout);
        window.clearTimeout(resetExpressionTimeout);
      };
    }

    setExpression("neutral");

    function scheduleNextExpression(delayMs: number): void {
      nextExpressionTimeout = window.setTimeout(() => {
        const nextExpression =
          expressions[Math.floor(Math.random() * expressions.length)];
        setExpression(nextExpression);

        const holdDuration =
          nextExpression === "blink" ? 180 : 420 + Math.random() * 520;
        resetExpressionTimeout = window.setTimeout(() => {
          setExpression("neutral");
          scheduleNextExpression(1800 + Math.random() * 3600);
        }, holdDuration);
      }, delayMs);
    }

    scheduleNextExpression(900);
    return () => {
      window.clearTimeout(nextExpressionTimeout);
      window.clearTimeout(resetExpressionTimeout);
    };
  }, [isWorking]);

  useEffect(() => {
    if (!isWorking) {
      setWorkingFrame(0);
      return () => undefined;
    }

    const intervalId = window.setInterval(() => {
      setWorkingFrame((current) => (current + 1) % 4);
    }, 140);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [isWorking]);

  function renderEyes(): ReactNode {
    switch (expression) {
      case "working": {
        const leftAngles = [-28, -10, 10, 28];
        const rightAngles = [28, 10, -10, -28];
        return (
          <>
            <g transform={`rotate(${leftAngles[workingFrame]} 35.5 46)`}>
              <path
                d="M35.5 39v14"
                fill="none"
                stroke="currentColor"
                strokeWidth="3.2"
                strokeLinecap="round"
              />
            </g>
            <g transform={`rotate(${rightAngles[workingFrame]} 60.5 46)`}>
              <path
                d="M60.5 39v14"
                fill="none"
                stroke="currentColor"
                strokeWidth="3.2"
                strokeLinecap="round"
              />
            </g>
          </>
        );
      }
      case "blink":
        return (
          <>
            <rect x="32.6" y="44.1" width="7.2" height="3.2" rx="1.6" fill="currentColor" />
            <rect x="56.2" y="44.1" width="7.2" height="3.2" rx="1.6" fill="currentColor" />
          </>
        );
      case "dots":
        return (
          <>
            <circle cx="36.2" cy="46" r="3.7" fill="currentColor" />
            <circle cx="59.8" cy="46" r="3.7" fill="currentColor" />
          </>
        );
      case "chevrons":
        return (
          <>
            <path
              d="M38.5 38.5 32.8 46 38.5 53.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="3.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M57.5 38.5 63.2 46 57.5 53.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="3.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </>
        );
      case "wink":
        return (
          <>
            <path
              d="M32.8 45.5h7.4"
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
              strokeLinecap="round"
            />
            <rect x="58" y="37.8" width="5.2" height="16.4" rx="2.6" fill="currentColor" />
          </>
        );
      default:
        return (
          <>
            <rect x="33.6" y="37.8" width="5.2" height="16.4" rx="2.6" fill="currentColor" />
            <rect x="57.2" y="37.8" width="5.2" height="16.4" rx="2.6" fill="currentColor" />
          </>
        );
    }
  }

  return (
    <svg viewBox="0 0 96 96" aria-hidden="true" className="brand-logo-svg">
      <path
        d="M48 10 73 23.5a12 12 0 0 1 6 10.5v28a12 12 0 0 1-6 10.5L48 86 23 72.5a12 12 0 0 1-6-10.5V34a12 12 0 0 1 6-10.5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g transform={`translate(${eyeOffset.x} ${eyeOffset.y})`}>
        {renderEyes()}
      </g>
      {expression === "smile" ? (
        <path
          d="M37.5 60.5c3 3.5 6.5 5.1 10.5 5.1s7.5-1.6 10.5-5.1"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.8"
          strokeLinecap="round"
        />
      ) : null}
      {expression === "wink" ? (
        <path
          d="M39.5 61c2.4 2.4 5.3 3.6 8.5 3.6s6.1-1.2 8.5-3.6"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      ) : null}
      {expression === "dots" ? (
        <path
          d="M42 62h12"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          opacity="0.8"
        />
      ) : null}
      {expression === "chevrons" ? (
        <path
          d="M42 60.5 48 64.5 54 60.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity="0.9"
        />
      ) : null}
      {expression === "blink" ? (
        <path
          d="M42.5 61.5h11"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          opacity="0.65"
        />
      ) : null}
      {expression === "working" ? (
        <>
          <path
            d="M43.8 61.1h8.4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            opacity="0.9"
          />
          <path
            d="M31.8 32.6c1.9-1.2 4-1.8 6.2-1.8"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            opacity="0.65"
          />
          <path
            d="M57.9 30.8c2.2 0 4.3.6 6.2 1.8"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            opacity="0.65"
          />
        </>
      ) : null}
      {expression === "neutral" ? (
        <path
          d="M42.5 61.8h11"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          opacity="0.35"
        />
      ) : null}
      {expression === "smile" ? (
        <circle cx="66.5" cy="33.5" r="1.5" fill="currentColor" opacity="0.3" />
      ) : null}
      {expression === "dots" ? (
        <circle cx="29.5" cy="35.5" r="1.3" fill="currentColor" opacity="0.35" />
      ) : null}
      {expression === "wink" ? (
        <circle cx="66.5" cy="34.5" r="1.2" fill="currentColor" opacity="0.28" />
      ) : null}
    </svg>
  );
}

function AssistantAvatarIcon() {
  return (
    <svg viewBox="0 0 96 96" aria-hidden="true" className="assistant-avatar-logo">
      <path
        d="M48 10 73 23.5a12 12 0 0 1 6 10.5v28a12 12 0 0 1-6 10.5L48 86 23 72.5a12 12 0 0 1-6-10.5V34a12 12 0 0 1 6-10.5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x="33.6" y="37.8" width="5.2" height="16.4" rx="2.6" fill="currentColor" />
      <rect x="57.2" y="37.8" width="5.2" height="16.4" rx="2.6" fill="currentColor" />
      <path
        d="M42.5 61.8h11"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        opacity="0.35"
      />
    </svg>
  );
}
