import {
  FormEvent,
  KeyboardEvent,
  MouseEvent,
  useEffect,
  useRef,
  useState
} from "react";

import {
  createSession,
  deleteSession,
  fetchModelCatalog,
  fetchSession,
  fetchSessions,
  sendMessage,
  updateSessionTitle,
  updateSessionModel
} from "./api";
import type {
  ChatMessage,
  ModelCatalogEntry,
  ModelCatalogResponse,
  ModelProvider,
  SessionDetail,
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

function providerLabel(provider: ModelProvider): string {
  return provider === "anthropic" ? "Claude" : "ChatGPT";
}

function messageAuthorLabel(role: ChatMessage["role"]): string {
  return role === "user" ? "You" : "Jeremy";
}

export default function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);
  const [modelCatalog, setModelCatalog] = useState<ModelCatalogResponse | null>(null);
  const [draft, setDraft] = useState("");
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isUpdatingModel, setIsUpdatingModel] = useState(false);
  const [sessionActionId, setSessionActionId] = useState<string | null>(null);
  const [openSessionMenuId, setOpenSessionMenuId] = useState<string | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeSession?.messages.length, isSending]);

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

  async function bootstrap(): Promise<void> {
    setIsBootstrapping(true);
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
    setError(null);
    try {
      const detail = await fetchSession(sessionId);
      setActiveSession(detail);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    }
  }

  async function handleNewChat(): Promise<void> {
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
    if (!activeSession || isUpdatingModel || isSending) {
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

  async function handleSend(event?: FormEvent): Promise<void> {
    event?.preventDefault();
    if (!activeSession || !draft.trim() || isSending) {
      return;
    }

    const content = draft.trim();
    setDraft("");
    setIsSending(true);
    setError(null);

    const optimisticUserMessage: ChatMessage = {
      id: `local-${crypto.randomUUID()}`,
      role: "user",
      content,
      created_at: new Date().toISOString()
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
      const response = await sendMessage(activeSession.session.id, content);
      setActiveSession((current) =>
        current
          ? {
              session: response.session,
              messages: [
                ...current.messages.filter(
                  (message) => message.id !== optimisticUserMessage.id
                ),
                response.user_message,
                response.assistant_message
              ]
            }
          : current
      );
      setSessions((current) =>
        current
          .map((session) =>
            session.id === response.session.id ? response.session : session
          )
          .sort((left, right) =>
            right.updated_at.localeCompare(left.updated_at)
          )
      );
    } catch (caughtError) {
      setDraft(content);
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
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error");
    } finally {
      setIsSending(false);
    }
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
      modelCatalog?.default_model_name
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
    <div className="app-shell">
      <aside className="session-rail">
        <div className="session-rail-top">
          <div className="brand-lockup">
            <div className="brand-mark">AJ</div>
            <div>
              <p className="section-label">Workspace</p>
              <h1>Ask Jeremy</h1>
            </div>
          </div>

          <button className="new-chat-button" onClick={() => void handleNewChat()}>
            New conversation
          </button>
        </div>

        <div className="rail-header">
          <p className="section-label">Conversations</p>
          <span>{sessions.length} total</span>
        </div>

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
                        <span className="session-updated">
                          {formatSessionTileTime(session.updated_at)}
                        </span>
                      </div>
                    </button>
                  )}

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
                </div>
              </section>
            );
          })}
        </div>
      </aside>

      <main className="chat-panel">
        <header className="chat-header">
          <div className="chat-header-inner">
            <div className="chat-title-block">
              <h2>{activeSession?.session.title ?? "Loading conversation"}</h2>
            </div>

            {activeSession ? (
              <div className="chat-controls">
                <label className="field-select">
                  <select
                    aria-label="Provider"
                    value={activeSession.session.model_provider}
                    onChange={(event) =>
                      void handleProviderChange(event.target.value as ModelProvider)
                    }
                    disabled={isUpdatingModel || isSending || !modelCatalog}
                  >
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                  </select>
                </label>

                <label className="field-select">
                  <select
                    aria-label="Model"
                    value={activeSession.session.model_name}
                    onChange={(event) => void handleModelChange(event.target.value)}
                    disabled={
                      isUpdatingModel || isSending || activeProviderModels.length === 0
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
                  here. Each session keeps its own model choice and message history.
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

            {activeSession?.messages.map((message) => (
              <article
                key={message.id}
                className={
                  message.role === "user" ? "message-row user" : "message-row assistant"
                }
              >
                <div className="message-avatar">
                  {message.role === "user" ? "YU" : "AJ"}
                </div>

                <div className="message-card">
                  <div className="message-meta">
                    <span>{messageAuthorLabel(message.role)}</span>
                    <span>{formatTime(message.created_at)}</span>
                  </div>
                  <div className="message-copy">{message.content}</div>
                </div>
              </article>
            ))}

            {isSending ? (
              <article className="message-row assistant pending">
                <div className="message-avatar">AJ</div>
                <div className="message-card">
                  <div className="message-meta">
                    <span>Jeremy</span>
                    <span>thinking</span>
                  </div>
                  <div className="message-copy">Working on it...</div>
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
                placeholder="Type your message to Ask Jeremy..."
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
