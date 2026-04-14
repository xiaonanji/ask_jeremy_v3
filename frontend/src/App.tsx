import {
  FormEvent,
  KeyboardEvent,
  type ReactNode,
  type ComponentPropsWithoutRef,
  type CSSProperties,
  memo,
  MouseEvent,
  useEffect,
  useMemo,
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

type StreamTraceState = {
  liveDraft: string;
  statusLines: string[];
};

type ParsedStreamingDraft = {
  leadingMarkdown: string;
  planItems: ParsedPlanItem[];
  trailingMarkdown: string;
};

type ParsedPlanItem = {
  slotKey: string;
  actionText: string;
  statusText: string;
  rawText: string;
};

type ArtifactPanelState = {
  messageId: string;
  messageCreatedAt: string;
  artifacts: ChatArtifact[];
};

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
  const [streamTrace, setStreamTrace] = useState<StreamTraceState | null>(null);
  const [artifactPanel, setArtifactPanel] = useState<ArtifactPanelState | null>(null);
  const [isSessionRailCollapsed, setIsSessionRailCollapsed] = useState(false);
  const [artifactPanelWidth, setArtifactPanelWidth] = useState(DEFAULT_ARTIFACT_PANEL_WIDTH);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const artifactPanelResizeRef = useRef<ArtifactPanelResizeState | null>(null);

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
    setStreamTrace(null);
    setArtifactPanel(null);
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
    setStreamTrace(null);
    setArtifactPanel(null);
    setError(null);
    try {
      const detail = await fetchSession(sessionId);
      setActiveSession(detail);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    }
  }

  async function handleNewChat(): Promise<void> {
    setStreamTrace(null);
    setArtifactPanel(null);
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

    setArtifactPanel({
      messageId: message.id,
      messageCreatedAt: message.created_at,
      artifacts: message.artifacts,
    });
  }

  function handleCloseArtifactPanel(): void {
    setArtifactPanel(null);
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
    setStreamTrace({
      liveDraft: "",
      statusLines: ["Waiting for the model response"]
    });
    setError(null);

    const optimisticUserMessage: ChatMessage = {
      id: `local-${crypto.randomUUID()}`,
      role: "user",
      content,
      created_at: new Date().toISOString(),
      artifacts: []
    };

    setActiveSession((current) =>
      current
        ? {
            ...current,
            messages: [...current.messages, optimisticUserMessage]
          }
        : current
    );

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

          setStreamTrace((current) => ({
            liveDraft: (current?.liveDraft ?? "") + delta,
            statusLines: current?.statusLines ?? []
          }));
          return;
        }

        if (eventName === "task_started") {
          const taskName = String((payload as { name?: unknown }).name ?? "");
          appendTraceStatusLine(describeTaskStatus(taskName, "started"));
          return;
        }

        if (eventName === "task_finished") {
          const taskName = String((payload as { name?: unknown }).name ?? "");
          const errorMessage = (payload as { error?: unknown }).error;
          appendTraceStatusLine(
            describeTaskStatus(
              taskName,
              "finished",
              typeof errorMessage === "string" ? errorMessage : null
            )
          );
          return;
        }

        if (eventName === "mcp_tool_call") {
          const serverName = String((payload as { server_name?: unknown }).server_name ?? "");
          const toolName = String((payload as { tool_name?: unknown }).tool_name ?? "");
          appendTraceStatusLine(`MCP: ${serverName} \u2192 ${toolName}`);
          return;
        }

        if (eventName === "error") {
          streamErrorMessage = String(
            (payload as { message?: unknown }).message ?? "Unknown stream error"
          );
          appendTraceStatusLine("Streaming error received");
          return;
        }

        if (eventName !== "done") {
          return;
        }

        didComplete = true;
        const donePayload = payload as {
          session: SessionMetadata;
          user_message: ChatMessage;
          assistant_message: ChatMessage;
        };

        setActiveSession((current) =>
          current
            ? {
                session: donePayload.session,
                messages: [
                  ...current.messages.filter(
                    (message) => message.id !== optimisticUserMessage.id
                  ),
                  donePayload.user_message,
                  donePayload.assistant_message
                ]
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
        setStreamTrace(null);
      });

      if (!didComplete) {
        if (streamErrorMessage) {
          throw new Error(streamErrorMessage);
        }
        throw new Error("The message stream ended before completion.");
      }
    } catch (caughtError) {
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
                  (message) => message.id !== optimisticUserMessage.id
                )
              }
            : current
        );
      }
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    } finally {
      setStreamTrace(null);
      setIsSending(false);
    }
  }

  function appendTraceStatusLine(line: string): void {
    if (!line) {
      return;
    }

    setStreamTrace((current) => {
      const existingLines = current?.statusLines ?? [];
      if (existingLines[existingLines.length - 1] === line) {
        return current ?? { liveDraft: "", statusLines: [line] };
      }

      return {
        liveDraft: current?.liveDraft ?? "",
        statusLines: [...existingLines, line].slice(-5)
      };
    });
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key !== "Enter") {
      return;
    }

    if (event.ctrlKey) {
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
                  <AppLogo isWorking={isSending || !!streamTrace} />
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

      <main className={artifactPanel ? "chat-panel artifact-panel-open" : "chat-panel"}>
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
                    disabled={isUpdatingDatabase || isUpdatingModel || isSending}
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

        <div
          className="chat-body"
          style={
            artifactPanel
              ? ({ "--artifact-panel-width": `${artifactPanelWidth}px` } as CSSProperties)
              : undefined
          }
        >
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
                    : activeSession
                      ? `Viewing ${activeSession.session.title}`
                      : "No session selected"}
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
                activeArtifactPanelMessageId={artifactPanel?.messageId ?? null}
                onOpenArtifactPanel={handleOpenArtifactPanel}
              />
            ) : null}

            {streamTrace ? (
              <article className="message-row assistant pending">
                <div className="message-avatar">
                  <AssistantAvatarIcon />
                </div>
                <div className="message-card">
                  <div className="message-meta">
                    <span>Jeremy</span>
                    <span>working</span>
                  </div>
                  <div className="stream-status-list">
                    {streamTrace.statusLines.map((line, index) => (
                      <div key={`${line}-${index}`} className="stream-status-line">
                        {line}
                      </div>
                    ))}
                  </div>
                  <div className="message-copy markdown-content">
                    <StreamingDraftContent
                      content={formatStreamingDraft(streamTrace.liveDraft) || "Working on it..."}
                    />
                  </div>
                </div>
              </article>
            ) : null}

            <div ref={messagesEndRef} />
              </div>
            </section>

            <footer className="composer-shell">
              <div className="composer-inner">
                {error ? <div className="error-banner">{error}</div> : null}

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
                    <div className="composer-hint">Enter to send, Ctrl+Enter for a new line</div>
                    <button type="submit" disabled={!draft.trim() || isSending || !activeSession}>
                      Send message
                    </button>
                  </div>
                </form>
              </div>
            </footer>
          </div>

          {artifactPanel && activeSession ? (
            <aside className="artifact-panel" aria-label="Artifact viewer">
              <div
                className="artifact-panel-resizer"
                onMouseDown={handleStartArtifactResize}
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize artifact panel"
              />
              <div className="artifact-panel-header">
                <div>
                  <p className="artifact-panel-kicker">Artifacts</p>
                  <h3>{formatArtifactCount(artifactPanel.artifacts.length)}</h3>
                  <p className="artifact-panel-subtitle">
                    Response at {formatTime(artifactPanel.messageCreatedAt)}
                  </p>
                </div>
                <button
                  type="button"
                  className="artifact-panel-close"
                  onClick={handleCloseArtifactPanel}
                >
                  Close
                </button>
              </div>

              <div className="artifact-preview-shell">
                {artifactPanel.artifacts.length > 0 ? (
                  <div className="artifact-preview-stack">
                    {artifactPanel.artifacts.map((artifact) => (
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
                          >
                            Open in new tab
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

  return phase === "started"
    ? `Running ${taskName || "task"}`
    : `${taskName || "Task"} complete`;
}

function formatStreamingDraft(value: string): string {
  if (!value.trim()) {
    return "";
  }

  const planCandidates = collectPlanCandidates(value);
  if (planCandidates.length <= 1) {
    return value;
  }

  const previousCandidate = value
    .slice(planCandidates[planCandidates.length - 2], planCandidates[planCandidates.length - 1])
    .trim();
  const latestCandidate = value.slice(planCandidates[planCandidates.length - 1]).trimStart();

  return mergePlanCandidates(previousCandidate, latestCandidate);
}

function collectPlanCandidates(value: string): number[] {
  const matches = Array.from(value.matchAll(/(?:\*\*Plan\*\*|Plan)/g));
  if (matches.length === 0) {
    return [];
  }

  const candidates: number[] = [];
  for (const match of matches) {
    const startIndex = match.index ?? 0;
    const lookahead = value.slice(startIndex, startIndex + 160);
    if (looksLikePlanSection(lookahead)) {
      candidates.push(startIndex);
    }
  }
  return candidates;
}

function looksLikePlanSection(value: string): boolean {
  if (!value.startsWith("Plan") && !value.startsWith("**Plan**")) {
    return false;
  }

  return /(?:^|\n|\r)\s*(?:[-*]\s|\d+\.\s)/.test(value) || value.length <= 12;
}

function formatArtifactCount(count: number): string {
  return count === 1 ? "1 output" : `${count} outputs`;
}

function formatArtifactTypeLabel(artifact: ChatArtifact): string {
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
  return artifact.filename.split(".").pop()?.toLowerCase() ?? "file";
}

function clampArtifactPanelWidth(width: number): number {
  return Math.min(MAX_ARTIFACT_PANEL_WIDTH, Math.max(MIN_ARTIFACT_PANEL_WIDTH, width));
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

function mergePlanCandidates(previousCandidate: string, latestCandidate: string): string {
  const previousDraft = parseStreamingDraft(previousCandidate);
  const latestDraft = parseStreamingDraft(latestCandidate);

  if (latestDraft.planItems.length === 0) {
    return latestCandidate;
  }

  const mergedItems = latestDraft.planItems.map((item) => item.rawText);
  for (let index = latestDraft.planItems.length; index < previousDraft.planItems.length; index += 1) {
    mergedItems.push(previousDraft.planItems[index].rawText);
  }

  const mergedParts = ["Plan", ...mergedItems.map((item) => `- ${item}`)];
  if (latestDraft.trailingMarkdown) {
    mergedParts.push(latestDraft.trailingMarkdown);
  }

  return mergedParts.join("\n").trim();
}

const MarkdownContent = memo(function MarkdownContent({ content }: { content: string }): ReactNode {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: (props: ComponentPropsWithoutRef<"a">) => (
          <a {...props} target="_blank" rel="noreferrer" />
        )
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
      <a href={previewUrl} target="_blank" rel="noreferrer">
        Open in new tab
      </a>
    </div>
  );
}

function StreamingDraftContent({ content }: { content: string }): ReactNode {
  const parsed = useMemo(() => parseStreamingDraft(content), [content]);
  if (parsed.planItems.length === 0) {
    return <MarkdownContent content={content} />;
  }

  return (
    <>
      {parsed.leadingMarkdown ? <MarkdownContent content={parsed.leadingMarkdown} /> : null}
      <StreamingPlanList items={parsed.planItems} />
      {parsed.trailingMarkdown ? <MarkdownContent content={parsed.trailingMarkdown} /> : null}
    </>
  );
}

const MessageRow = memo(function MessageRow({
  message,
  isArtifactPanelMessage,
  onOpenArtifactPanel,
}: {
  message: ChatMessage;
  isArtifactPanelMessage: boolean;
  onOpenArtifactPanel: (message: ChatMessage) => void;
}): ReactNode {
  return (
    <article
      className={
        message.role === "user" ? "message-row user" : "message-row assistant"
      }
    >
      {message.role === "assistant" ? (
        <div className="message-avatar">
          <AssistantAvatarIcon />
        </div>
      ) : null}

      <div className="message-card">
        <div className="message-meta">
          <span>{messageAuthorLabel(message.role)}</span>
          <span>{formatTime(message.created_at)}</span>
        </div>
        <div
          className={
            message.role === "assistant"
              ? "message-copy markdown-content"
              : "message-copy plain-text"
          }
        >
          {message.role === "assistant" ? (
            <MarkdownContent content={message.content} />
          ) : (
            message.content
          )}
        </div>
        {message.role === "assistant" && message.artifacts.length > 0 ? (
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
            >
              Preview
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
  onOpenArtifactPanel,
}: {
  messages: ChatMessage[];
  activeArtifactPanelMessageId: string | null;
  onOpenArtifactPanel: (message: ChatMessage) => void;
}): ReactNode {
  return (
    <>
      {messages.map((message) => (
        <MessageRow
          key={message.id}
          message={message}
          isArtifactPanelMessage={activeArtifactPanelMessageId === message.id}
          onOpenArtifactPanel={onOpenArtifactPanel}
        />
      ))}
    </>
  );
});

function parseStreamingDraft(value: string): ParsedStreamingDraft {
  const planHeaderMatch = value.match(/(?:^|\n)(\*\*Plan\*\*|Plan)\s*(?:\n|$)/);
  if (!planHeaderMatch || planHeaderMatch.index === undefined) {
    return {
      leadingMarkdown: value,
      planItems: [],
      trailingMarkdown: ""
    };
  }

  const headerStart = planHeaderMatch.index + (planHeaderMatch[0].startsWith("\n") ? 1 : 0);
  const headerEnd = headerStart + planHeaderMatch[1].length;
  const leadingMarkdown = value.slice(0, headerStart).trim();
  const afterHeader = value.slice(headerEnd).trimStart();
  const lines = afterHeader.split(/\r?\n/);
  const planItems: ParsedPlanItem[] = [];
  const trailingLines: string[] = [];
  let currentItemLines: string[] = [];
  let planItemIndex = 0;
  let parsingPlanItems = true;

  for (const line of lines) {
    const bulletMatch = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (parsingPlanItems && bulletMatch) {
      if (currentItemLines.length > 0) {
        const itemText = currentItemLines.join(" ").trim();
        planItems.push(parsePlanItem(itemText, planItemIndex));
        planItemIndex += 1;
      }
      currentItemLines = [bulletMatch[1].trim()];
      continue;
    }

    if (parsingPlanItems && currentItemLines.length > 0 && line.trim()) {
      currentItemLines.push(line.trim());
      continue;
    }

    if (parsingPlanItems && currentItemLines.length > 0) {
      const itemText = currentItemLines.join(" ").trim();
      planItems.push(parsePlanItem(itemText, planItemIndex));
      planItemIndex += 1;
      currentItemLines = [];
    }

    parsingPlanItems = false;
    trailingLines.push(line);
  }

  if (parsingPlanItems && currentItemLines.length > 0) {
    const itemText = currentItemLines.join(" ").trim();
    planItems.push(parsePlanItem(itemText, planItemIndex));
  }

  return {
    leadingMarkdown,
    planItems,
    trailingMarkdown: trailingLines.join("\n").trim()
  };
}

function parsePlanItem(value: string, index: number): ParsedPlanItem {
  const match = value.match(/^(.*?)(?:\s+-\s+(not started|in progress|completed))$/i);
  if (!match) {
    return {
      slotKey: `plan-item-${index}`,
      actionText: value,
      statusText: "",
      rawText: value
    };
  }

  return {
    slotKey: `plan-item-${index}`,
    actionText: match[1].trim(),
    statusText: match[2],
    rawText: value
  };
}

const StreamingPlanList = memo(function StreamingPlanList({
  items
}: {
  items: ParsedPlanItem[];
}): ReactNode {
  return (
    <div className="stream-plan-block">
      <div className="stream-plan-title">Plan</div>
      <ul className="stream-plan-list">
        {items.map((item) => (
          <StreamingPlanRow
            key={item.slotKey}
            actionText={item.actionText}
            statusText={item.statusText}
            rawText={item.rawText}
          />
        ))}
      </ul>
    </div>
  );
});

const StreamingPlanRow = memo(function StreamingPlanRow({
  actionText,
  statusText,
  rawText
}: {
  actionText: string;
  statusText: string;
  rawText: string;
}): ReactNode {
  if (!statusText) {
    return <li className="stream-plan-item">{rawText}</li>;
  }

  return (
    <li className="stream-plan-item">
      <span className="stream-plan-action">{actionText}</span>
      <span className="stream-plan-separator"> - </span>
      <span className="stream-plan-status">{statusText}</span>
    </li>
  );
});

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
