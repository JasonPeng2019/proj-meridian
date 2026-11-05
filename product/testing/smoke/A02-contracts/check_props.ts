// Compile on Actions with contracts.ts and generated fixtures.ts; no app/build.
import type {
  CustomerPage, CustomerReviewStatus, DebugAccess, DebugContext, EvidenceProps,
  FactTools, PartPageProps, ReviewProps, ShellNavigationItem, Viewer3DProps,
  WarningListProps, PrepRunner, Determiner, Verifier, MachineSummarizer, CostSummarizer,
  ApiClient, ApiCalls, ChatProps, ConversationDetail, ConversationSendResponse, ConversationServiceFactory,
} from "../../../development/frontend/src/contracts";

declare const reviewWithoutDebug: Omit<ReviewProps, "debug">;
// @ts-expect-error Review requires explicit enabled Debug access.
const review: ReviewProps = reviewWithoutDebug;
// @ts-expect-error Review is not ordinary customer navigation.
const page: CustomerPage = "review";
// @ts-expect-error Review lives inside Debug, not a shell navigation tab.
const navigation: ShellNavigationItem = "review";
// @ts-expect-error Customer labels cannot expose engineering review queues.
const label: CustomerReviewStatus = "Needs human review";
// @ts-expect-error Default-disabled Debug cannot expose actions.
const disabled: DebugAccess = {enabled: false};
// @ts-expect-error Engineering warnings require enabled Debug access.
const warnings: WarningListProps = {warnings: []};
declare const evidenceWithoutDebug: Omit<EvidenceProps, "debug">;
const evidence: EvidenceProps = evidenceWithoutDebug;
declare const partWithoutDebug: Omit<PartPageProps, "debug">;
const part: PartPageProps = partWithoutDebug;
declare const viewerWithoutDebug: Omit<Viewer3DProps, "debug">;
const viewer: Viewer3DProps = viewerWithoutDebug;
const hidden: DebugContext = {enabled: false};

declare const tools: FactTools;
const machine = tools.machine_summary();
const cost = tools.cost_summary();
declare const runner: PrepRunner;
declare const determine: Determiner;
declare const verify: Verifier;
declare const summarizeMachine: MachineSummarizer;
declare const summarizeCost: CostSummarizer;
declare const api: ApiClient;
const list = api.conversations();
const created: Promise<ConversationDetail> = api.create_conversation();
const reopened = api.conversation({conversation_id: "synthetic-thread-a"});
const sent: Promise<ConversationSendResponse> = api.send_conversation(
  {conversation_id: "synthetic-thread-a"}, {message: "Synthetic continuation"});
declare const chatWithoutSelection: Omit<ChatProps, "selected_conversation_id" | "on_select_conversation">;
// @ts-expect-error A04 owns explicit selected-thread state and transitions.
const noSelection: ChatProps = chatWithoutSelection;
declare const chat: ChatProps;
chat.on_select_conversation("synthetic-thread-b");
chat.on_open_part({conversation_id: "synthetic-thread-a", part_id: "D-013/part"});
// @ts-expect-error Late part callbacks must identify their owning thread.
chat.on_open_part({part_id: "D-013/part"});
chat.on_open_source({kind: "part", name: "D-013/part", part_id: "D-013/part"}, "synthetic-thread-a");
// @ts-expect-error New send shape never accepts client history.
const forged: ApiCalls["send_conversation"]["body"] = {message: "Synthetic", history: []};
// @ts-expect-error Read shape never exposes the server-owned ledger.
const leaked: ConversationDetail = {conversation: {conversation_id: "synthetic", title: "Synthetic", created_at: "2000-01-01T00:00:00Z", updated_at: "2000-01-01T00:00:00Z"}, messages: [], ledger: {}};
declare const serviceFactory: ConversationServiceFactory;
void [review, page, navigation, label, disabled, warnings, evidence, part, viewer,
  hidden, machine, cost, runner, determine, verify, summarizeMachine, summarizeCost,
  list, created, reopened, sent, noSelection, chat, forged, leaked, serviceFactory];
