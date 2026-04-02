import { realpathSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const PLUGIN_ID = "reel-agent-bridge";
const ENTRY_REAL_PATH = realpathSync(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = path.dirname(ENTRY_REAL_PATH);
const DEFAULT_REPO_ROOT = path.resolve(PLUGIN_ROOT, "../../..");
const DEFAULT_TELEGRAM_ACCOUNT_ID = "realtor-social";
const DEFAULT_WORKSPACE_STATE_PATH = path.join(
  process.env.HOME || path.dirname(DEFAULT_REPO_ROOT),
  ".openclaw",
  "workspace-realtor-social",
  ".openclaw",
  "reel-agent-bridge-state.json",
);
const STATE_REL_PATH = ["plugins", PLUGIN_ID, "state.json"];

type BridgeConfig = {
  callbackSecret: string;
  telegramAccountId: string;
  repoRoot: string;
  workspaceStatePath: string;
  mediaLocalRoots: string[];
  repoEnvPath: string;
};

type BackendConfig = {
  reelAgentUrl: string;
  reelAgentToken: string;
  callbackBaseUrl?: string;
  dailyTriggerSecret?: string;
};

type TargetBinding = {
  target: string;
  accountId?: string;
  senderId?: string;
  messageId?: string;
  replyToMessageId?: number;
  updatedAt: string;
};

type LastDelivery = {
  jobId: string;
  caption?: string;
  videoUrl?: string;
  videoPath?: string;
  sceneCount?: number;
  wordCount?: number;
  aspectRatio?: string;
  updatedAt: string;
};

type LastDailyInsight = {
  headline?: string;
  caption?: string;
  imageUrls?: Record<string, string>;
  updatedAt: string;
};

type ListingStyle = "elegant" | "professional" | "energetic";

type PendingListingVideo = {
  firstPhotoPath: string;
  photoDir: string;
  photoCountHint?: number;
  style?: ListingStyle;
  awaiting: "style_selection" | "confirmation";
  updatedAt: string;
};

type LastListingVideoInput = {
  firstPhotoPath: string;
  photoDir: string;
  style: ListingStyle;
  updatedAt: string;
};

type AgentState = {
  agentPhone: string;
  target?: string;
  accountId?: string;
  lastJobId?: string;
  lastDelivery?: LastDelivery;
  lastDailyInsight?: LastDailyInsight;
  pendingListingVideo?: PendingListingVideo;
  lastListingVideoInput?: LastListingVideoInput;
  sessionContext?: {
    currentLane?: "listing_video" | "daily_insight" | "onboarding";
    lastSuccessfulPath?: string;
    starterTaskCompleted?: boolean;
    lastPostRenderKind?: "delivered" | "daily_insight" | "failed";
    listingVideoDeliveredAt?: string;
    lastInsightPublishedAt?: string;
    videoHandoffNudgedAt?: string;
  };
  updatedAt: string;
};

type RouterDebugEntry = {
  senderId: string;
  accountId?: string;
  conversationId?: string;
  rawText: string;
  normalizedText?: string;
  handled: boolean;
  reason:
    | "missing_sender_or_conversation"
    | "handler_error"
    | "handled_help"
    | "handled_trust_first"
    | "handled_daily_control"
    | "handled_daily_insight"
    | "handled_property_content"
    | "handled_daily_publish"
    | "handled_daily_skip"
    | "handled_daily_refine"
    | "handled_video_publish"
    | "handled_video_redo"
    | "handled_video_feedback"
    | "handled_listing_photos_auto"
    | "handled_listing_photos_style_request"
    | "handled_listing_style_selected"
    | "handled_listing_confirm"
    | "no_match";
  updatedAt: string;
};

type BridgeState = {
  version: 1;
  routesByMessageId: Record<string, TargetBinding>;
  routesByPhone: Record<string, TargetBinding>;
  agents: Record<string, AgentState>;
  targets: Record<string, AgentState>;
  lastRouterDebug?: RouterDebugEntry;
  updatedAt: string;
};

type BridgePayloadBase = {
  type?: string;
  agent_phone?: string;
  openclaw_msg_id?: string;
};

type ProgressPayload = BridgePayloadBase & {
  type: "progress";
  job_id: string;
  step?: string;
  message?: string;
};

type DeliveredPayload = BridgePayloadBase & {
  type: "delivered";
  job_id: string;
  video_url?: string;
  video_path?: string;
  caption?: string;
  scene_count?: number;
  word_count?: number;
  aspect_ratio?: string;
};

type FailedPayload = BridgePayloadBase & {
  type: "failed";
  job_id: string;
  error?: string;
  retry_count?: number;
  override_url?: string;
};

type DailyInsightPayload = BridgePayloadBase & {
  type: "daily_insight";
  insight?: {
    topic?: string;
    headline?: string;
    caption?: string;
    hashtags?: string[];
    cta?: string;
    content_type?: string;
  };
  image_urls?: Record<string, string>;
  agent_name?: string;
};

type OnboardingFormPayload = BridgePayloadBase & {
  type: "onboarding_form";
  agent_name?: string;
  form_url?: string;
  message?: string;
};

type FormCompletedPayload = BridgePayloadBase & {
  type: "form_completed";
  agent_name?: string;
  message?: string;
};

type BridgePayload =
  | ProgressPayload
  | DeliveredPayload
  | FailedPayload
  | DailyInsightPayload
  | OnboardingFormPayload
  | FormCompletedPayload;

type EventContext = {
  api: Parameters<Exclude<Parameters<typeof definePluginEntry>[0]["register"], undefined>>[0];
  config: BridgeConfig;
  statePath: string;
};

function nowIso(): string {
  return new Date().toISOString();
}

function defaultState(): BridgeState {
  return {
    version: 1,
    routesByMessageId: {},
    routesByPhone: {},
    agents: {},
    targets: {},
    updatedAt: nowIso(),
  };
}

function defaultRepoEnvPath(repoRoot: string): string {
  return path.join(repoRoot, ".env");
}

function defaultMediaLocalRoots(repoRoot: string): string[] {
  return [repoRoot, path.join(repoRoot, "skills", "listing-video", "output"), "/tmp"];
}

function normalizePluginConfig(raw: Record<string, unknown> | undefined): BridgeConfig {
  const callbackSecret = typeof raw?.callbackSecret === "string" ? raw.callbackSecret.trim() : "";
  if (!callbackSecret) {
    throw new Error("reel-agent-bridge requires plugins.entries.reel-agent-bridge.config.callbackSecret");
  }

  const repoRoot =
    typeof raw?.repoRoot === "string" && raw.repoRoot.trim()
      ? path.resolve(raw.repoRoot.trim())
      : DEFAULT_REPO_ROOT;

  return {
    callbackSecret,
    telegramAccountId:
      typeof raw?.telegramAccountId === "string" && raw.telegramAccountId.trim()
        ? raw.telegramAccountId.trim()
        : DEFAULT_TELEGRAM_ACCOUNT_ID,
    repoRoot,
    workspaceStatePath:
      typeof raw?.workspaceStatePath === "string" && raw.workspaceStatePath.trim()
        ? path.resolve(raw.workspaceStatePath.trim())
        : DEFAULT_WORKSPACE_STATE_PATH,
    mediaLocalRoots: Array.isArray(raw?.mediaLocalRoots)
      ? raw.mediaLocalRoots
          .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
          .map((item) => path.resolve(item))
      : defaultMediaLocalRoots(repoRoot),
    repoEnvPath:
      typeof raw?.repoEnvPath === "string" && raw.repoEnvPath.trim()
        ? path.resolve(raw.repoEnvPath.trim())
        : defaultRepoEnvPath(repoRoot),
  };
}

async function loadRepoEnv(repoEnvPath: string): Promise<BackendConfig> {
  const env: Record<string, string> = {};
  try {
    const text = await readFile(repoEnvPath, "utf8");
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) {
        continue;
      }
      const idx = line.indexOf("=");
      if (idx < 0) {
        continue;
      }
      const key = line.slice(0, idx).trim();
      let value = line.slice(idx + 1).trim();
      if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      env[key] = value;
    }
  } catch {
    // fall through to process env
  }

  const reelAgentUrl = (env.REEL_AGENT_URL || process.env.REEL_AGENT_URL || "").trim();
  const reelAgentToken = (env.REEL_AGENT_TOKEN || process.env.REEL_AGENT_TOKEN || "").trim();
  if (!reelAgentUrl || !reelAgentToken) {
    throw new Error("Missing REEL_AGENT_URL or REEL_AGENT_TOKEN for reel-agent-bridge router");
  }

  return {
    reelAgentUrl,
    reelAgentToken,
    callbackBaseUrl: (env.OPENCLAW_CALLBACK_BASE_URL || process.env.OPENCLAW_CALLBACK_BASE_URL || "").trim() || undefined,
    dailyTriggerSecret: (env.DAILY_TRIGGER_SECRET || process.env.DAILY_TRIGGER_SECRET || "").trim() || undefined,
  };
}

async function backendFetchJson(
  backend: BackendConfig,
  pathName: string,
  init: RequestInit = {},
): Promise<any> {
  const headers = new Headers(init.headers || {});
  headers.set("Authorization", `Bearer ${backend.reelAgentToken}`);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${backend.reelAgentUrl.replace(/\/$/, "")}${pathName}`, {
    ...init,
    headers,
  });
  const text = await response.text();
  let body: any = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { raw: text };
  }
  if (!response.ok) {
    throw new Error(`Backend ${response.status} ${pathName}: ${typeof body?.detail === "string" ? body.detail : text}`);
  }
  return body;
}

async function loadProfileStyle(backend: BackendConfig, agentPhone: string): Promise<ListingStyle | undefined> {
  try {
    const body = await backendFetchJson(backend, `/api/profile/${encodeURIComponent(agentPhone)}`, {
      method: "GET",
    });
    const style = typeof body?.style === "string" ? body.style.trim().toLowerCase() : "";
    if (style === "elegant" || style === "professional" || style === "energetic") {
      return style;
    }
    return undefined;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.includes("Backend 404 /api/profile/")) {
      return undefined;
    }
    throw error;
  }
}

async function loadState(statePath: string): Promise<BridgeState> {
  try {
    const text = await readFile(statePath, "utf8");
    const parsed = JSON.parse(text) as Partial<BridgeState>;
    return {
      ...defaultState(),
      ...parsed,
      routesByMessageId: parsed.routesByMessageId ?? {},
      routesByPhone: parsed.routesByPhone ?? {},
      agents: parsed.agents ?? {},
      targets: parsed.targets ?? {},
    };
  } catch {
    return defaultState();
  }
}

async function writeJsonFile(filePath: string, value: unknown): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, JSON.stringify(value, null, 2) + "\n", "utf8");
}

async function persistState(statePath: string, state: BridgeState, workspaceStatePath?: string): Promise<void> {
  state.updatedAt = nowIso();
  await writeJsonFile(statePath, state);
  if (workspaceStatePath) {
    await writeJsonFile(workspaceStatePath, {
      updatedAt: state.updatedAt,
      agents: state.agents,
      targets: state.targets,
      lastRouterDebug: state.lastRouterDebug,
    });
  }
}

async function readJsonBody(req: import("node:http").IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
  }
  const body = Buffer.concat(chunks).toString("utf8").trim();
  if (!body) {
    return {};
  }
  return JSON.parse(body);
}

function sendJson(res: import("node:http").ServerResponse, status: number, body: unknown): boolean {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(body));
  return true;
}

function parseReplyToMessageId(messageId?: string): number | undefined {
  if (!messageId) {
    return undefined;
  }
  const parsed = Number.parseInt(messageId, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function pickTelegramTarget(event: {
  channel?: string;
  conversationId?: string;
  isGroup?: boolean;
  senderId?: string;
  metadata?: Record<string, unknown>;
}): string | undefined {
  const fromConversation = event.conversationId?.trim();
  if (fromConversation) {
    return fromConversation;
  }

  const metadata = event.metadata ?? {};
  const chatId =
    typeof metadata.chat_id === "string" || typeof metadata.chat_id === "number"
      ? String(metadata.chat_id).trim()
      : undefined;
  const threadId =
    typeof metadata.message_thread_id === "number"
      ? metadata.message_thread_id
      : typeof metadata.message_thread_id === "string"
        ? Number.parseInt(metadata.message_thread_id, 10)
        : undefined;

  if (chatId) {
    return event.isGroup && Number.isFinite(threadId) ? `${chatId}:topic:${threadId}` : chatId;
  }

  return event.senderId?.trim() || undefined;
}

function upsertAgentState(
  state: BridgeState,
  agentPhone: string,
  binding: TargetBinding,
  patch: Partial<AgentState>,
): void {
  const updatedAt = nowIso();
  const merged: AgentState = {
    agentPhone,
    updatedAt,
    target: binding.target,
    accountId: binding.accountId,
    ...state.agents[agentPhone],
    ...patch,
    agentPhone,
    target: patch.target ?? binding.target,
    accountId: patch.accountId ?? binding.accountId,
    updatedAt,
  };
  state.agents[agentPhone] = merged;
  if (merged.target) {
    state.targets[merged.target] = merged;
  }
}

function resolveBinding(state: BridgeState, payload: BridgePayloadBase): TargetBinding | undefined {
  if (payload.openclaw_msg_id && state.routesByMessageId[payload.openclaw_msg_id]) {
    return state.routesByMessageId[payload.openclaw_msg_id];
  }
  if (payload.agent_phone && state.routesByPhone[payload.agent_phone]) {
    return state.routesByPhone[payload.agent_phone];
  }
  if (payload.agent_phone && state.agents[payload.agent_phone]?.target) {
    const agent = state.agents[payload.agent_phone];
    return {
      target: agent.target!,
      accountId: agent.accountId,
      updatedAt: agent.updatedAt,
    };
  }
  if (payload.agent_phone) {
    return {
      target: payload.agent_phone,
      updatedAt: nowIso(),
    };
  }
  return undefined;
}

function firstNonEmptyString(...values: Array<string | undefined>): string | undefined {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return undefined;
}

function pickMediaRef(...values: Array<string | undefined>): string | undefined {
  return firstNonEmptyString(...values);
}

function renderProgressText(payload: ProgressPayload): string {
  const step = payload.step?.trim();
  const message = payload.message?.trim();
  if (message && step) {
    return `⏳ ${message}\nStep: ${step}\nJob: ${payload.job_id}`;
  }
  if (message) {
    return `⏳ ${message}\nJob: ${payload.job_id}`;
  }
  if (step) {
    return `⏳ Working on your request...\nStep: ${step}\nJob: ${payload.job_id}`;
  }
  return `⏳ Working on your request...\nJob: ${payload.job_id}`;
}

function renderDeliveredText(payload: DeliveredPayload): string {
  const stats = [
    typeof payload.scene_count === "number" ? `Scenes: ${payload.scene_count}` : "",
    typeof payload.word_count === "number" ? `Words: ${payload.word_count}` : "",
    payload.aspect_ratio ? `Ratio: ${payload.aspect_ratio}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const lines = ["🎬 Your listing video is ready!"];
  if (payload.caption?.trim()) {
    lines.push("", payload.caption.trim());
  }
  if (stats) {
    lines.push("", stats);
  }
  lines.push("", "Reply with:", "- publish", "- adjust <what to change>", "- redo");
  return lines.join("\n");
}

function renderDeliveredPublishText(lastDelivery?: LastDelivery): string {
  const lines = ["Great choice! Here's your caption for posting 📱"];
  if (lastDelivery?.caption?.trim()) {
    lines.push("", lastDelivery.caption.trim());
  }
  lines.push("", "If you want another cut, reply with:", "- adjust <what to change>", "- redo");
  return lines.join("\n");
}

function renderFailedText(payload: FailedPayload): string {
  const lines = ["⚠️ The video job failed."];
  if (payload.error?.trim()) {
    lines.push("", payload.error.trim());
  }
  if (typeof payload.retry_count === "number") {
    lines.push("", `Retry count: ${payload.retry_count}`);
  }
  if (payload.override_url?.trim()) {
    lines.push("", `Ops override: ${payload.override_url.trim()}`);
  }
  lines.push("", "Please retry later or send a fresh request.");
  return lines.join("\n");
}

function isHelpLike(text: string): boolean {
  if (["what can you do", "what do you do"].some((token) => text.includes(token))) {
    return true;
  }
  return ["help", "hi", "hello", "start"].some((token) => new RegExp(`(^|\\s)${token}(\\s|$)`, "i").test(text));
}

function isTrustFirstQuestion(text: string): boolean {
  return ["is this an app", "secure", "how much", "price", "first step"].some((token) => text.includes(token));
}

function isDailyInsightRequest(text: string): boolean {
  return ["daily insight", "market insight", "market update", "insight"].some((token) => text.includes(token));
}

function isPropertyContentText(text: string): boolean {
  const signals = ["open house", "listing", "bed", "bath", "sqft", "mls", "just listed"];
  const hasSignal = signals.some((token) => text.includes(token));
  const hasAddressLike = /\d+\s+.+(st|street|ave|avenue|rd|road|dr|drive|blvd|lane|ln)\b/i.test(text);
  return hasSignal || hasAddressLike;
}

function parseListingStyle(text: string): ListingStyle | undefined {
  if (text.includes("elegant")) {
    return "elegant";
  }
  if (text.includes("professional")) {
    return "professional";
  }
  if (text.includes("energetic")) {
    return "energetic";
  }
  return undefined;
}

function isConfirm(text: string): boolean {
  return /(^|\s)(go|ok|yes|start|confirm)(\s|$)/i.test(text);
}

function parsePhotoCountHint(text: string): number | undefined {
  const match = text.match(/\((\d+)\s+images?\)/i);
  if (!match) {
    return undefined;
  }
  const parsed = Number.parseInt(match[1] ?? "", 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function extractMediaPath(metadata: Record<string, unknown> | undefined): string | undefined {
  const value = metadata?.mediaPath;
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function extractMediaType(metadata: Record<string, unknown> | undefined): string | undefined {
  const value = metadata?.mediaType;
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function buildCallbackUrl(backend: BackendConfig): string | undefined {
  return backend.callbackBaseUrl ? `${backend.callbackBaseUrl.replace(/\/$/, "")}/events` : undefined;
}

function renderStyleSelectionReply(photoCountHint?: number): string {
  const photoLine =
    typeof photoCountHint === "number" ? `Got ${photoCountHint} photos. ` : "Got your photos. ";
  return [
    `${photoLine}Pick a style first:`,
    "• elegant ✨",
    "• professional 💼",
    "• energetic 🔥",
  ].join("\n");
}

async function startListingVideoJob(
  backend: BackendConfig,
  senderId: string,
  photoPath: string,
  style: ListingStyle,
): Promise<{ job_id: string; status: string }> {
  const payload: Record<string, unknown> = {
    agent_phone: senderId,
    photo_paths: [photoPath],
    params: { style },
  };
  const callbackUrl = buildCallbackUrl(backend);
  if (callbackUrl) {
    payload.callback_url = callbackUrl;
  }
  return backendFetchJson(backend, "/webhook/in", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

async function restartListingVideoJob(
  backend: BackendConfig,
  senderId: string,
  lastInput: LastListingVideoInput | undefined,
): Promise<{ job_id: string; status: string } | undefined> {
  if (!lastInput?.firstPhotoPath || !lastInput.style) {
    return undefined;
  }
  return startListingVideoJob(backend, senderId, lastInput.firstPhotoPath, lastInput.style);
}

function isStopPush(text: string): boolean {
  return ["stop push", "pause push", "disable daily"].some((token) => text.includes(token));
}

function isResumePush(text: string): boolean {
  return ["resume push", "start push", "enable daily"].some((token) => text.includes(token));
}

function isPublish(text: string): boolean {
  return ["publish", "post"].includes(text);
}

function isRedo(text: string): boolean {
  return ["redo", "again"].includes(text);
}

function isSkip(text: string): boolean {
  return ["skip", "pass"].includes(text);
}

function isInsightRefineShorter(text: string): boolean {
  return text === "shorter";
}

function isInsightRefineProfessional(text: string): boolean {
  return text === "more professional" || text === "professional";
}

function renderTrustFirstReply(): string {
  return [
    "It’s not a big app setup — you can just text me here.",
    "Send 6-10 listing photos and I’ll turn them into a video, or say 'daily insight' for a ready-to-post market update.",
    "You don’t need to fill a form to get started.",
  ].join("\n\n");
}

function renderHelpReply(): string {
  return [
    "I can turn listing photos into a marketing video, or draft a ready-to-post daily insight for you.",
    "Send 6-10 listing photos to start a video, or say 'daily insight' to get today's market content.",
  ].join("\n\n");
}

function renderDailyInsightText(payload: DailyInsightPayload): string {
  const insight = payload.insight ?? {};
  const hashtags = Array.isArray(insight.hashtags) && insight.hashtags.length > 0 ? insight.hashtags.join(" ") : "";
  const lines = ["📈 Daily insight is ready."];
  if (payload.agent_name?.trim()) {
    lines[0] = `📈 Daily insight is ready for ${payload.agent_name.trim()}.`;
  }
  if (insight.headline?.trim()) {
    lines.push("", insight.headline.trim());
  }
  if (insight.caption?.trim()) {
    lines.push("", insight.caption.trim());
  }
  if (hashtags) {
    lines.push("", hashtags);
  }
  if (insight.cta?.trim()) {
    lines.push("", `CTA: ${insight.cta.trim()}`);
  }
  lines.push("", "Reply with:", "- publish", "- skip", "- shorter", "- more professional");
  return lines.join("\n");
}

function renderInsightToVideoHandoff(): string {
  return "Nice! By the way — whenever you have a listing, just send 6-10 photos and I'll make a video too.";
}

function ensureRenderableDailyInsight(payload: DailyInsightPayload): void {
  const headline = payload.insight?.headline?.trim();
  const caption = payload.insight?.caption?.trim();
  const imageUrls = payload.image_urls
    ? Object.values(payload.image_urls).filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    : [];

  if (!headline) {
    throw new Error("daily_insight missing insight.headline");
  }
  if (!caption) {
    throw new Error("daily_insight missing insight.caption");
  }
  if (imageUrls.length < 1) {
    throw new Error("daily_insight missing image_urls");
  }
}

function renderOnboardingFormText(payload: OnboardingFormPayload): string {
  if (payload.message?.trim()) {
    return payload.message.trim();
  }
  const lines = ["📝 Your onboarding form is ready."];
  if (payload.form_url?.trim()) {
    lines.push("", payload.form_url.trim());
  }
  return lines.join("\n");
}

function renderFormCompletedText(payload: FormCompletedPayload): string {
  if (payload.message?.trim()) {
    return payload.message.trim();
  }
  return payload.agent_name?.trim()
    ? `✅ ${payload.agent_name.trim()} completed onboarding.`
    : "✅ Onboarding form completed.";
}

async function sendTelegramMessage(
  api: EventContext["api"],
  config: BridgeConfig,
  binding: TargetBinding,
  text: string,
  mediaUrl?: string,
): Promise<void> {
  const send = api.runtime?.channel?.telegram?.sendMessageTelegram;
  if (!send) {
    throw new Error("telegram runtime unavailable");
  }

  await send(binding.target, text, {
    accountId: binding.accountId ?? config.telegramAccountId,
    ...(binding.replyToMessageId ? { replyToMessageId: binding.replyToMessageId } : {}),
    ...(mediaUrl ? { mediaUrl } : {}),
    ...(config.mediaLocalRoots.length > 0 ? { mediaLocalRoots: config.mediaLocalRoots } : {}),
  });
}

function ensureString(value: unknown, fieldName: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${fieldName} is required`);
  }
  return value.trim();
}

function normalizePayload(raw: unknown): BridgePayload {
  if (!raw || typeof raw !== "object") {
    throw new Error("JSON object body required");
  }
  const payload = raw as Record<string, unknown>;
  const type = ensureString(payload.type, "type");

  switch (type) {
    case "progress":
      return {
        type,
        job_id: ensureString(payload.job_id, "job_id"),
        agent_phone: typeof payload.agent_phone === "string" ? payload.agent_phone.trim() : undefined,
        openclaw_msg_id: typeof payload.openclaw_msg_id === "string" ? payload.openclaw_msg_id.trim() : undefined,
        step: typeof payload.step === "string" ? payload.step.trim() : undefined,
        message: typeof payload.message === "string" ? payload.message.trim() : undefined,
      };
    case "delivered":
      return {
        type,
        job_id: ensureString(payload.job_id, "job_id"),
        agent_phone: typeof payload.agent_phone === "string" ? payload.agent_phone.trim() : undefined,
        openclaw_msg_id: typeof payload.openclaw_msg_id === "string" ? payload.openclaw_msg_id.trim() : undefined,
        video_url: typeof payload.video_url === "string" ? payload.video_url.trim() : undefined,
        video_path: typeof payload.video_path === "string" ? payload.video_path.trim() : undefined,
        caption: typeof payload.caption === "string" ? payload.caption : undefined,
        scene_count: typeof payload.scene_count === "number" ? payload.scene_count : undefined,
        word_count: typeof payload.word_count === "number" ? payload.word_count : undefined,
        aspect_ratio: typeof payload.aspect_ratio === "string" ? payload.aspect_ratio.trim() : undefined,
      };
    case "failed":
      return {
        type,
        job_id: ensureString(payload.job_id, "job_id"),
        agent_phone: typeof payload.agent_phone === "string" ? payload.agent_phone.trim() : undefined,
        openclaw_msg_id: typeof payload.openclaw_msg_id === "string" ? payload.openclaw_msg_id.trim() : undefined,
        error: typeof payload.error === "string" ? payload.error : undefined,
        retry_count: typeof payload.retry_count === "number" ? payload.retry_count : undefined,
        override_url: typeof payload.override_url === "string" ? payload.override_url.trim() : undefined,
      };
    case "daily_insight":
      return {
        type,
        agent_phone: typeof payload.agent_phone === "string" ? payload.agent_phone.trim() : undefined,
        openclaw_msg_id: typeof payload.openclaw_msg_id === "string" ? payload.openclaw_msg_id.trim() : undefined,
        insight: typeof payload.insight === "object" && payload.insight ? (payload.insight as DailyInsightPayload["insight"]) : undefined,
        image_urls:
          typeof payload.image_urls === "object" && payload.image_urls
            ? (payload.image_urls as Record<string, string>)
            : undefined,
        agent_name: typeof payload.agent_name === "string" ? payload.agent_name : undefined,
      };
    case "onboarding_form":
      return {
        type,
        agent_phone: typeof payload.agent_phone === "string" ? payload.agent_phone.trim() : undefined,
        openclaw_msg_id: typeof payload.openclaw_msg_id === "string" ? payload.openclaw_msg_id.trim() : undefined,
        agent_name: typeof payload.agent_name === "string" ? payload.agent_name : undefined,
        form_url: typeof payload.form_url === "string" ? payload.form_url : undefined,
        message: typeof payload.message === "string" ? payload.message : undefined,
      };
    case "form_completed":
      return {
        type,
        agent_phone: typeof payload.agent_phone === "string" ? payload.agent_phone.trim() : undefined,
        openclaw_msg_id: typeof payload.openclaw_msg_id === "string" ? payload.openclaw_msg_id.trim() : undefined,
        agent_name: typeof payload.agent_name === "string" ? payload.agent_name : undefined,
        message: typeof payload.message === "string" ? payload.message : undefined,
      };
    default:
      throw new Error(`Unsupported event type: ${type}`);
  }
}

async function handleBridgePayload(ctx: EventContext, state: BridgeState, payload: BridgePayload): Promise<{ target: string }> {
  const binding = resolveBinding(state, payload);
  if (!binding) {
    throw new Error(
      `No Telegram target binding for type=${payload.type} agent_phone=${payload.agent_phone ?? "unknown"} openclaw_msg_id=${payload.openclaw_msg_id ?? "unknown"}`,
    );
  }

  switch (payload.type) {
    case "progress": {
      await sendTelegramMessage(ctx.api, ctx.config, binding, renderProgressText(payload));
      if (payload.agent_phone) {
        upsertAgentState(state, payload.agent_phone, binding, {
          lastJobId: payload.job_id,
          sessionContext: {
            ...state.agents[payload.agent_phone]?.sessionContext,
            currentLane: "listing_video",
          },
        });
      }
      break;
    }
    case "delivered": {
      const mediaRef = pickMediaRef(payload.video_url, payload.video_path);
      await sendTelegramMessage(ctx.api, ctx.config, binding, renderDeliveredText(payload), mediaRef);
      if (payload.agent_phone) {
        upsertAgentState(state, payload.agent_phone, binding, {
          lastJobId: payload.job_id,
          lastDelivery: {
            jobId: payload.job_id,
            caption: payload.caption,
            videoUrl: payload.video_url,
            videoPath: payload.video_path,
            sceneCount: payload.scene_count,
            wordCount: payload.word_count,
            aspectRatio: payload.aspect_ratio,
            updatedAt: nowIso(),
          },
          sessionContext: {
            ...state.agents[payload.agent_phone]?.sessionContext,
            currentLane: "listing_video",
            lastSuccessfulPath: "listing_video.delivered",
            starterTaskCompleted: true,
            lastPostRenderKind: "delivered",
            listingVideoDeliveredAt: nowIso(),
          },
        });
      }
      break;
    }
    case "failed": {
      await sendTelegramMessage(ctx.api, ctx.config, binding, renderFailedText(payload));
      if (payload.agent_phone) {
        upsertAgentState(state, payload.agent_phone, binding, {
          lastJobId: payload.job_id,
          sessionContext: {
            ...state.agents[payload.agent_phone]?.sessionContext,
            lastPostRenderKind: "failed",
          },
        });
      }
      break;
    }
    case "daily_insight": {
      ensureRenderableDailyInsight(payload);
      const imageRef = payload.image_urls
        ? Object.values(payload.image_urls).find((value) => typeof value === "string" && value.trim())
        : undefined;
      await sendTelegramMessage(ctx.api, ctx.config, binding, renderDailyInsightText(payload), imageRef);
      if (payload.agent_phone) {
        upsertAgentState(state, payload.agent_phone, binding, {
          lastDailyInsight: {
            headline: payload.insight?.headline,
            caption: payload.insight?.caption,
            imageUrls: payload.image_urls,
            updatedAt: nowIso(),
          },
          sessionContext: {
            ...state.agents[payload.agent_phone]?.sessionContext,
            currentLane: "daily_insight",
            lastSuccessfulPath: "daily_insight.rendered",
            lastPostRenderKind: "daily_insight",
          },
        });
      }
      break;
    }
    case "onboarding_form": {
      await sendTelegramMessage(ctx.api, ctx.config, binding, renderOnboardingFormText(payload));
      break;
    }
    case "form_completed": {
      await sendTelegramMessage(ctx.api, ctx.config, binding, renderFormCompletedText(payload));
      break;
    }
  }

  if (payload.type === "daily_insight" && payload.agent_phone) {
    const sessionContext = state.agents[payload.agent_phone]?.sessionContext;
    if (sessionContext?.lastInsightPublishedAt && !sessionContext.videoHandoffNudgedAt) {
      await sendTelegramMessage(ctx.api, ctx.config, binding, renderInsightToVideoHandoff());
      upsertAgentState(state, payload.agent_phone, binding, {
        sessionContext: {
          ...sessionContext,
          videoHandoffNudgedAt: nowIso(),
        },
      });
    }
  }

  return { target: binding.target };
}

async function handleRouterMessage(
  ctx: EventContext,
  state: BridgeState,
  binding: TargetBinding,
  senderId: string,
  rawText: string,
  metadata?: Record<string, unknown>,
): Promise<{ handled: boolean; text?: string; reason: RouterDebugEntry["reason"]; normalizedText?: string }> {
  const text = rawText.trim().toLowerCase();
  const backend = await loadRepoEnv(ctx.config.repoEnvPath);
  const agentState = state.agents[senderId];
  const sessionContext = agentState?.sessionContext ?? {};
  const pendingListing = agentState?.pendingListingVideo;
  const mediaPath = extractMediaPath(metadata);
  const mediaType = extractMediaType(metadata);

  if (mediaPath && mediaType?.startsWith("image/")) {
    const photoDir = path.dirname(mediaPath);
    const photoCountHint = parsePhotoCountHint(rawText);
    const profileStyle = await loadProfileStyle(backend, senderId);
    if (profileStyle) {
      const job = await startListingVideoJob(backend, senderId, mediaPath, profileStyle);
      upsertAgentState(state, senderId, binding, {
        lastJobId: typeof job?.job_id === "string" ? job.job_id : agentState?.lastJobId,
        lastListingVideoInput: {
          firstPhotoPath: mediaPath,
          photoDir,
          style: profileStyle,
          updatedAt: nowIso(),
        },
        pendingListingVideo: undefined,
        sessionContext: {
          ...sessionContext,
          currentLane: "listing_video",
          lastSuccessfulPath: "listing_video.started",
        },
      });
      return {
        handled: true,
        text: `Got your photos! Using your ${profileStyle} style... 🎬\nVideo will be ready in ~3 min.`,
        reason: "handled_listing_photos_auto",
        normalizedText: text,
      };
    }

    upsertAgentState(state, senderId, binding, {
      pendingListingVideo: {
        firstPhotoPath: mediaPath,
        photoDir,
        photoCountHint,
        awaiting: "style_selection",
        updatedAt: nowIso(),
      },
      sessionContext: {
        ...sessionContext,
        currentLane: "listing_video",
        lastSuccessfulPath: "listing_video.awaiting_style",
      },
    });
    return {
      handled: true,
      text: renderStyleSelectionReply(photoCountHint),
      reason: "handled_listing_photos_style_request",
      normalizedText: text,
    };
  }

  if (!text) {
    return { handled: false, reason: "no_match", normalizedText: text };
  }

  if (pendingListing?.awaiting === "style_selection") {
    const selectedStyle = parseListingStyle(text);
    if (selectedStyle) {
      upsertAgentState(state, senderId, binding, {
        pendingListingVideo: {
          ...pendingListing,
          style: selectedStyle,
          awaiting: "confirmation",
          updatedAt: nowIso(),
        },
        sessionContext: {
          ...sessionContext,
          currentLane: "listing_video",
          lastSuccessfulPath: "listing_video.style_selected",
        },
      });
      return {
        handled: true,
        text: `Style set to ${selectedStyle} ✨\nReply with 'go' when you're ready.`,
        reason: "handled_listing_style_selected",
        normalizedText: text,
      };
    }
  }

  if (pendingListing?.awaiting === "confirmation" && pendingListing.style && isConfirm(text)) {
    const job = await startListingVideoJob(backend, senderId, pendingListing.firstPhotoPath, pendingListing.style);
    upsertAgentState(state, senderId, binding, {
      lastJobId: typeof job?.job_id === "string" ? job.job_id : agentState?.lastJobId,
      lastListingVideoInput: {
        firstPhotoPath: pendingListing.firstPhotoPath,
        photoDir: pendingListing.photoDir,
        style: pendingListing.style,
        updatedAt: nowIso(),
      },
      pendingListingVideo: undefined,
      sessionContext: {
        ...sessionContext,
        currentLane: "listing_video",
        lastSuccessfulPath: "listing_video.started",
      },
    });
    return {
      handled: true,
      text: "Starting video generation... 🎬",
      reason: "handled_listing_confirm",
      normalizedText: text,
    };
  }

  if (isHelpLike(text)) {
    return { handled: true, text: renderHelpReply(), reason: "handled_help", normalizedText: text };
  }

  if (isTrustFirstQuestion(text)) {
    return { handled: true, text: renderTrustFirstReply(), reason: "handled_trust_first", normalizedText: text };
  }

  if (isStopPush(text) || isResumePush(text)) {
    const action = isStopPush(text) ? "disable_daily_push" : "enable_daily_push";
    await backendFetchJson(backend, "/webhook/in", {
      method: "POST",
      body: JSON.stringify({
        agent_phone: senderId,
        photo_paths: [],
        params: { action },
      }),
    });
    return {
      handled: true,
      text: isStopPush(text)
        ? "Daily insights paused ✅ Say 'resume push' anytime to restart."
        : "Daily insights resumed! You'll get tomorrow's content at 8 AM 📬",
      reason: "handled_daily_control",
      normalizedText: text,
    };
  }

  if (isDailyInsightRequest(text)) {
    await backendFetchJson(backend, `/api/daily-trigger?secret=${encodeURIComponent(backend.dailyTriggerSecret ?? "")}`, {
      method: "POST",
    });
    upsertAgentState(state, senderId, binding, {
      sessionContext: {
        ...sessionContext,
        currentLane: "daily_insight",
      },
    });
    return {
      handled: true,
      text: "Got it — I’m preparing a ready-to-post daily insight for you. 📈",
      reason: "handled_daily_insight",
      normalizedText: text,
    };
  }

  if (isPropertyContentText(text)) {
    upsertAgentState(state, senderId, binding, {
      sessionContext: {
        ...sessionContext,
        currentLane: "listing_video",
        lastSuccessfulPath: "property_content.started",
      },
    });
    return {
      handled: true,
      text: "Got it — this looks like a property content request. Send 6-10 photos when you're ready and I’ll take it from there. 🏡",
      reason: "handled_property_content",
      normalizedText: text,
    };
  }

  if (sessionContext.lastPostRenderKind === "daily_insight") {
    if (isPublish(text)) {
      upsertAgentState(state, senderId, binding, {
        sessionContext: {
          ...sessionContext,
          lastInsightPublishedAt: nowIso(),
          videoHandoffNudgedAt: sessionContext.videoHandoffNudgedAt ?? nowIso(),
        },
      });
      return {
        handled: true,
        text: [
          "Looks good — publishing this daily insight now. 📈",
          renderInsightToVideoHandoff(),
        ].join("\n\n"),
        reason: "handled_daily_publish",
        normalizedText: text,
      };
    }
    if (isSkip(text)) {
      return {
        handled: true,
        text: "Skipped this daily insight. We can use the next one instead. ⏭️",
        reason: "handled_daily_skip",
        normalizedText: text,
      };
    }
    if (isInsightRefineShorter(text) || isInsightRefineProfessional(text)) {
      const feedbackText = isInsightRefineShorter(text) ? "shorter" : "more professional";
      await backendFetchJson(backend, "/webhook/feedback", {
        method: "POST",
        body: JSON.stringify({
          agent_phone: senderId,
          feedback_text: feedbackText,
          feedback_scope: "insight",
          callback_url: `${(backend.callbackBaseUrl ?? "").replace(/\/$/, "")}/events`,
        }),
      });
      return {
        handled: true,
        text: isInsightRefineShorter(text)
          ? "Got it — tightening this daily insight now. ✂️"
          : "Got it — making this daily insight more polished now. ✨",
        reason: "handled_daily_refine",
        normalizedText: text,
      };
    }
  }

  if (sessionContext.lastPostRenderKind === "delivered" && agentState?.lastJobId) {
    if (isPublish(text)) {
      upsertAgentState(state, senderId, binding, {
        sessionContext: {
          ...sessionContext,
          currentLane: "listing_video",
          lastSuccessfulPath: "listing_video.published",
        },
      });
      return {
        handled: true,
        text: renderDeliveredPublishText(agentState?.lastDelivery),
        reason: "handled_video_publish",
        normalizedText: text,
      };
    }
    if (isRedo(text)) {
      const job = await restartListingVideoJob(backend, senderId, agentState?.lastListingVideoInput);
      if (!job) {
        return {
          handled: true,
          text: "I don't have the last photo set on hand yet. Please send the listing photos again and I'll restart from scratch. 🔄",
          reason: "handled_video_redo",
          normalizedText: text,
        };
      }
      upsertAgentState(state, senderId, binding, {
        lastJobId: typeof job?.job_id === "string" ? job.job_id : agentState?.lastJobId,
        sessionContext: {
          ...sessionContext,
          currentLane: "listing_video",
          lastSuccessfulPath: "listing_video.redo_started",
        },
      });
      return {
        handled: true,
        text: "Starting from scratch with your photos... 🔄",
        reason: "handled_video_redo",
        normalizedText: text,
      };
    }
    await backendFetchJson(backend, "/webhook/feedback", {
      method: "POST",
      body: JSON.stringify({
        job_id: agentState.lastJobId,
        agent_phone: senderId,
        feedback_text: rawText.trim(),
        feedback_scope: "video",
      }),
    });
    return {
      handled: true,
      text: "Got it — adjusting now... ⚡",
      reason: "handled_video_feedback",
      normalizedText: text,
    };
  }

  return { handled: false, reason: "no_match", normalizedText: text };
}

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "Reel Agent Bridge",
  description: "Deterministic Telegram bridge for Reel Agent callbacks",
  register(api) {
    const config = normalizePluginConfig(api.pluginConfig);
    const statePath = path.join(api.runtime.state.resolveStateDir(), ...STATE_REL_PATH);

    api.logger.info?.(`${PLUGIN_ID}: register account=${config.telegramAccountId} statePath=${statePath}`);

    api.on("gateway_start", () => {
      api.logger.info?.(`${PLUGIN_ID}: gateway_start account=${config.telegramAccountId}`);
    });

    api.on("inbound_claim", async (event) => {
      if (event.channel !== "telegram") {
        return;
      }

      const target = pickTelegramTarget(event);
      if (!target) {
        return;
      }

      const binding: TargetBinding = {
        target,
        accountId: event.accountId?.trim() || undefined,
        senderId: event.senderId?.trim() || undefined,
        messageId: event.messageId?.trim() || undefined,
        replyToMessageId: parseReplyToMessageId(event.messageId),
        updatedAt: nowIso(),
      };

      const state = await loadState(statePath);
      if (binding.messageId) {
        state.routesByMessageId[binding.messageId] = binding;
      }
      if (binding.senderId) {
        state.routesByPhone[binding.senderId] = binding;
        upsertAgentState(state, binding.senderId, binding, {});
      }
      await persistState(statePath, state, config.workspaceStatePath);
    });

    api.on("before_dispatch", async (event, hookCtx) => {
      if (event.channel !== "telegram" || hookCtx.accountId !== config.telegramAccountId || event.isGroup) {
        return;
      }
      const senderId = hookCtx.senderId?.trim();
      const conversationId = hookCtx.conversationId?.trim();
      if (!senderId || !conversationId) {
        const state = await loadState(statePath);
        state.lastRouterDebug = {
          senderId: senderId ?? "",
          accountId: hookCtx.accountId?.trim() || config.telegramAccountId,
          conversationId: conversationId ?? undefined,
          rawText: event.content ?? event.body ?? "",
          normalizedText: (event.content ?? event.body ?? "").trim().toLowerCase(),
          handled: false,
          reason: "missing_sender_or_conversation",
          updatedAt: nowIso(),
        };
        await persistState(statePath, state, config.workspaceStatePath);
        api.logger.info?.(`${PLUGIN_ID}: before_dispatch skipped missing sender/conversation`);
        return;
      }

      const binding: TargetBinding = {
        target: conversationId,
        accountId: hookCtx.accountId?.trim() || config.telegramAccountId,
        senderId,
        updatedAt: nowIso(),
      };

      const state = await loadState(statePath);
      state.routesByPhone[senderId] = binding;
      upsertAgentState(state, senderId, binding, {});
      const rawText = event.content ?? event.body ?? "";
      try {
        const result = await handleRouterMessage(
          { api, config, statePath },
          state,
          binding,
          senderId,
          rawText,
          event.metadata,
        );
        state.lastRouterDebug = {
          senderId,
          accountId: hookCtx.accountId?.trim() || config.telegramAccountId,
          conversationId,
          rawText,
          normalizedText: result.normalizedText,
          handled: result.handled,
          reason: result.reason,
          updatedAt: nowIso(),
        };
        await persistState(statePath, state, config.workspaceStatePath);
        if (result.handled) {
          api.logger.info?.(
            `${PLUGIN_ID}: before_dispatch handled sender=${senderId} account=${hookCtx.accountId ?? ""} reason=${result.reason} text=${JSON.stringify(rawText.slice(0, 120))}`,
          );
          return { handled: true, text: result.text };
        }
        api.logger.info?.(
          `${PLUGIN_ID}: before_dispatch no_match sender=${senderId} account=${hookCtx.accountId ?? ""} text=${JSON.stringify(rawText.slice(0, 120))}`,
        );
        return;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        state.lastRouterDebug = {
          senderId,
          accountId: hookCtx.accountId?.trim() || config.telegramAccountId,
          conversationId,
          rawText,
          normalizedText: rawText.trim().toLowerCase(),
          handled: false,
          reason: "handler_error",
          updatedAt: nowIso(),
        };
        await persistState(statePath, state, config.workspaceStatePath);
        api.logger.warn?.(
          `${PLUGIN_ID}: before_dispatch error sender=${senderId} account=${hookCtx.accountId ?? ""} message=${message}`,
        );
        return;
      }
    });

    api.registerHttpRoute({
      path: "/reel-agent/events",
      auth: "plugin",
      async handler(req, res) {
        if (req.method !== "POST") {
          res.statusCode = 405;
          res.setHeader("Allow", "POST");
          res.end("Method Not Allowed");
          return true;
        }

        const providedSecret = req.headers["x-reel-secret"];
        const provided =
          Array.isArray(providedSecret) ? providedSecret[0]?.trim() : typeof providedSecret === "string" ? providedSecret.trim() : "";

        if (!provided || provided !== config.callbackSecret) {
          return sendJson(res, 401, { ok: false, error: "invalid_secret" });
        }

        try {
          const rawPayload = await readJsonBody(req);
          const payload = normalizePayload(rawPayload);
          const state = await loadState(statePath);
          const result = await handleBridgePayload({ api, config, statePath }, state, payload);
          await persistState(statePath, state, config.workspaceStatePath);
          return sendJson(res, 200, {
            ok: true,
            type: payload.type,
            target: result.target,
            statePath,
          });
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          api.logger.warn?.(`${PLUGIN_ID}: route error ${message}`);
          const status = message.includes("No Telegram target binding") ? 404 : message.includes("Unsupported event type") ? 400 : 400;
          return sendJson(res, status, { ok: false, error: message });
        }
      },
    });
  },
});
