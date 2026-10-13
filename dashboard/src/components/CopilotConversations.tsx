import { ArrowLeft } from "lucide-react";
import { api } from "../api";
import { NO_CONVERSATIONS } from "../copilot";
import { dateTime } from "../format";
import { useLoad } from "../useLoad";
import { StateMessage } from "./StateMessage";

// The handler's earlier conversations, newest first, each titled with its first
// question, read when the list opens.
export function CopilotConversations({
  current,
  onOpen,
  onBack,
}: Readonly<{
  current?: string;
  onOpen: (conversationId: string) => void;
  onBack: () => void;
}>) {
  const { data: conversations, error } = useLoad(api.listConversations);
  return (
    <div className="earlier">
      <button type="button" className="earlier-back" onClick={onBack}>
        <ArrowLeft aria-hidden />
        Back
      </button>
      <h3>Earlier conversations</h3>
      {!conversations || conversations.length === 0 ? (
        <StateMessage error={error} empty={conversations && NO_CONVERSATIONS} />
      ) : (
        <ul className="earlier-list">
          {conversations.map((conversation) => (
            <li key={conversation.conversation_id}>
              <button
                type="button"
                className="earlier-item"
                aria-current={
                  conversation.conversation_id === current ? "true" : undefined
                }
                onClick={() => {
                  onOpen(conversation.conversation_id);
                }}
              >
                <span className="earlier-title">{conversation.title}</span>
                <span className="muted small">
                  {dateTime(conversation.created_at)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
