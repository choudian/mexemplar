import type { AssistantMeetingTranscript, AssistantMeetingParticipant } from "../../api/assistantTasks";

interface MeetingChannelDrawerProps {
  meeting: AssistantMeetingTranscript | null;
  loading?: boolean;
  onClose?: () => void;
}

const MEETING_STATUS_LABELS: Record<string, string> = {
  open: "进行中",
  concluded: "已达成结论",
  closed_timeout: "因超时结束",
  closed_abandoned: "已放弃",
};

function resolveSenderLabel(
  senderId: string,
  participants?: AssistantMeetingParticipant[],
): string {
  const match = participants?.find((p) => p.id === senderId);
  return match?.label ?? "协作者";
}

export function MeetingChannelDrawer({
  meeting,
  loading = false,
  onClose,
}: MeetingChannelDrawerProps) {
  if (!meeting && !loading) {
    return null;
  }
  return (
    <aside className="assistant-collab-panel assistant-meeting-drawer" aria-label="协作会议">
      <header>
        <strong>协作会议</strong>
        <button type="button" onClick={onClose}>
          关闭
        </button>
      </header>
      {loading ? <div role="status">正在加载会议记录</div> : null}
      {meeting ? (
        <>
          <div>
            <span>{MEETING_STATUS_LABELS[meeting.status] ?? "已结束"}</span>
            <span>
              {meeting.turnsUsed}/{meeting.turnBudget}
            </span>
          </div>
          <ol>
            {meeting.messages.map((message) => (
              <li key={message.sequence}>
                <b>{resolveSenderLabel(message.senderId, meeting.participants)}</b>
                <p>{message.content}</p>
              </li>
            ))}
          </ol>
          {meeting.conclusion ? <p>{meeting.conclusion}</p> : null}
        </>
      ) : null}
    </aside>
  );
}
