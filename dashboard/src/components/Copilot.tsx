import {
  BotMessageSquare,
  History,
  PanelRightClose,
  SquarePen,
} from "lucide-react";
import {
  type ReactNode,
  type RefObject,
  use,
  useCallback,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
} from "react";
import { type Handler, api } from "../api";
import {
  ASK_EVERY_MS,
  OPENING,
  OVERLAY,
  TURN_STATES,
  saveConversation,
  saveOpen,
  savedConversation,
  savedOpen,
  waitingFor,
} from "../copilot";
import {
  type ConfirmationAnswer,
  type Conversation,
  latestTurn,
  stillWorking,
} from "../conversation";
import { HandlerContext } from "../handler";
import { ApiError } from "../refusals";
import { useAction } from "../useAction";
import { useLoad } from "../useLoad";
import { CopilotConversations } from "./CopilotConversations";
import { CopilotGreeting } from "./CopilotGreeting";
import { CopilotTurn } from "./CopilotTurn";
import { MessageBox } from "./MessageBox";
import { StateMessage } from "./StateMessage";

// The conversation open, if any, read about once a second while the Copilot
// works on it, and not otherwise. One just started shows as the app gave it
// back until it has been read.
function useConversation(conversationId?: string, started?: Conversation) {
  const load = useCallback(
    () =>
      conversationId === undefined
        ? Promise.resolve(undefined)
        : api.getConversation(conversationId),
    [conversationId],
  );
  const { data, error, reload, show } = useLoad<Conversation | undefined>(
    load,
    ASK_EVERY_MS,
    stillWorking,
  );
  const fresh =
    started?.conversation_id === conversationId ? started : undefined;
  return { conversation: data ?? fresh, error, reload, show };
}

// Keeps the newest of a conversation in view as it grows.
function useScrolledToTheEnd(conversation?: Conversation) {
  const end = useRef<HTMLDivElement>(null);
  const turn = latestTurn(conversation);
  const growth = [
    conversation?.conversation_id,
    conversation?.turns.length,
    turn?.steps.length,
    turn?.status,
  ].join(":");
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [growth]);
  return end;
}

// On a narrow window, where the sidebar sits over the page, Escape pressed in it
// collapses it.
function useCollapseOnEscape(
  sidebar: RefObject<HTMLElement | null>,
  collapse: () => void,
) {
  const onKeyDown = useEffectEvent((event: KeyboardEvent) => {
    const inSidebar =
      event.target instanceof Node && sidebar.current?.contains(event.target);
    if (event.key === "Escape" && inSidebar && matchMedia(OVERLAY).matches)
      collapse();
  });
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      onKeyDown(event);
    };
    document.addEventListener("keydown", listener);
    return () => {
      document.removeEventListener("keydown", listener);
    };
  }, []);
}

// The Copilot, in a sidebar on the right of every signed-in page, open the first
// time and collapsed to a slim tab when the handler chooses, which the browser
// remembers for each handler, with the conversation open.
export function Copilot() {
  const handler = use(HandlerContext);
  return handler ? <Sidebar handler={handler} /> : null;
}

function Sidebar({ handler }: Readonly<{ handler: Handler }>) {
  const id = handler.handler_id;
  const [open, setOpen] = useState(() => savedOpen(id));
  const [chosen, setChosen] = useState(() => savedConversation(id));
  // Counts the conversations the handler has opened, so each starts afresh.
  const [opened, setOpened] = useState(0);
  const [earlier, setEarlier] = useState(false);
  const sidebar = useRef<HTMLElement>(null);
  const tab = useRef<HTMLButtonElement>(null);
  const toggled = useRef(false);

  // Once the handler opens or collapses the sidebar, the keyboard carries on
  // from the sidebar, or from its tab.
  useEffect(() => {
    if (!toggled.current) return;
    toggled.current = false;
    (open ? sidebar : tab).current?.focus();
  }, [open]);

  useCollapseOnEscape(sidebar, () => {
    openOrCollapse(false);
  });

  function openOrCollapse(next: boolean) {
    saveOpen(id, next);
    toggled.current = true;
    setOpen(next);
  }

  function started(conversationId: string) {
    saveConversation(id, conversationId);
    setChosen(conversationId);
  }

  function choose(conversationId?: string) {
    saveConversation(id, conversationId);
    setChosen(conversationId);
    setOpened(opened + 1);
    setEarlier(false);
  }

  if (!open)
    return (
      <button
        ref={tab}
        type="button"
        className="copilot-tab"
        aria-label="Open the Copilot"
        onClick={() => {
          openOrCollapse(true);
        }}
      >
        <BotMessageSquare aria-hidden />
        <span>Copilot</span>
      </button>
    );

  return (
    <aside ref={sidebar} tabIndex={-1} className="copilot" aria-label="Copilot">
      <div className="copilot-bar">
        <p className="copilot-title">
          <span className="copilot-mark">
            <BotMessageSquare aria-hidden />
          </span>
          Copilot
        </p>
        <button
          type="button"
          className="icon-button"
          aria-label="New conversation"
          title="New conversation"
          onClick={() => {
            choose();
          }}
        >
          <SquarePen aria-hidden />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="Earlier conversations"
          title="Earlier conversations"
          aria-pressed={earlier}
          onClick={() => {
            setEarlier(!earlier);
          }}
        >
          <History aria-hidden />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="Collapse the Copilot"
          title="Collapse"
          onClick={() => {
            openOrCollapse(false);
          }}
        >
          <PanelRightClose aria-hidden />
        </button>
      </div>
      <ConversationPane
        key={opened}
        handler={handler}
        conversationId={chosen}
        onStarted={started}
        instead={
          earlier ? (
            <CopilotConversations
              current={chosen}
              onOpen={choose}
              onBack={() => {
                setEarlier(false);
              }}
            />
          ) : undefined
        }
      />
    </aside>
  );
}

// The conversation open, or the greeting when there's none, and the box to ask
// in. One the app no longer has, as after a reseed, counts as none, so the next
// message starts a new one. A screen reader is told where the latest turn
// stands, once, rather than every card as it changes.
function ConversationPane({
  handler,
  conversationId: chosen,
  onStarted,
  instead,
}: Readonly<{
  handler: Handler;
  conversationId?: string;
  onStarted: (conversationId: string) => void;
  // What the sidebar shows in place of the conversation, if anything.
  instead?: ReactNode;
}>) {
  const [started, setStarted] = useState<Conversation>();
  const [answered, setAnswered] = useState<string>();
  const { conversation, error, reload, show } = useConversation(
    chosen,
    started,
  );
  const gone = error instanceof ApiError && error.status === 404;
  const conversationId = gone ? undefined : chosen;
  const opening =
    conversationId !== undefined && !conversation && error === undefined;
  const latest = latestTurn(conversation);
  const end = useScrolledToTheEnd(conversation);

  useEffect(() => {
    if (gone) saveConversation(handler.handler_id, undefined);
  }, [gone, handler.handler_id]);

  // What the app gives back for a message or an answer shows at once. When it
  // refuses, the conversation is read again, as the turn may have failed, with why.
  async function showOrReread(sending: Promise<Conversation>) {
    try {
      show(await sending);
    } catch (refusal) {
      reload();
      throw refusal;
    }
  }

  const message = useAction(async (text: string) => {
    if (conversationId === undefined) {
      const first = await api.startConversation(text);
      setStarted(first);
      onStarted(first.conversation_id);
    } else await showOrReread(api.sendMessage(conversationId, text));
  });
  const answer = useAction(
    async (turnId: string, given: ConfirmationAnswer) => {
      if (conversationId === undefined) return;
      setAnswered(turnId);
      await showOrReread(api.answerConfirmation(conversationId, turnId, given));
    },
  );

  function body() {
    if (conversationId === undefined)
      return (
        <CopilotGreeting
          name={handler.name}
          onAsk={(question) => {
            void message.run(question);
          }}
          disabled={message.sending}
        />
      );
    if (!conversation) return <StateMessage error={error} />;
    return (
      <ol className="turns" aria-label="Conversation">
        {conversation.turns.map((turn) => (
          <CopilotTurn
            key={turn.turn_id}
            turn={turn}
            onAnswer={(turnId, given) => {
              void answer.run(turnId, given);
            }}
            answering={answer.sending}
            answerError={turn.turn_id === answered ? answer.error : undefined}
          />
        ))}
      </ol>
    );
  }

  return (
    <>
      <div className="copilot-body">
        {instead ?? body()}
        <div ref={end} />
      </div>
      <p className="visually-hidden" role="status">
        {latest && instead === undefined ? TURN_STATES[latest.status] : ""}
      </p>
      <div className="copilot-foot">
        <MessageBox
          onSend={message.run}
          waitingFor={
            waitingFor(conversation) ?? (opening ? OPENING : undefined)
          }
          sending={message.sending}
          error={message.error}
        />
        <p className="signed-in-as">Signed in as {handler.name}</p>
      </div>
    </>
  );
}
