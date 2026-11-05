// Compile on Actions with contracts.ts and generated fixtures.ts; no app/build.
import type {
  CustomerPage, CustomerReviewStatus, DebugAccess, DebugContext, EvidenceProps,
  FactTools, PartPageProps, ReviewProps, ShellNavigationItem, Viewer3DProps,
  WarningListProps, PrepRunner, Determiner, Verifier, MachineSummarizer, CostSummarizer,
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
void [review, page, navigation, label, disabled, warnings, evidence, part, viewer,
  hidden, machine, cost, runner, determine, verify, summarizeMachine, summarizeCost];
