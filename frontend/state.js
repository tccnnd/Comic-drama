// ─── Application State & Constants ───────────────────────────────────────────

export const API = {
  projects: "/api/projects",
  voiceCatalog: "/api/voice-catalog",
  ttsProviders: "/api/tts-providers",
  comfyuiStatus: "/api/comfyui/status",
  voicePreview: "/api/voice-preview",
  fillMissingAssets: "/api/projects",
  repairStoryText: "/api/projects",
  applyScriptPreview: "/api/projects",
};

export const TIMELINE_PX_PER_SECOND = 72;
export const MIN_SCENE_DURATION = 1;
export const DEFAULT_CROP_BOX = { x: 0, y: 0, width: 1, height: 1 };

export const state = {
  projects: [],
  project: null,
  currentProjectId: "",
  selectedSceneOrder: 1,
  selectedCharacterIndex: 1,
  activeTab: "plan",
  voiceCatalog: [],
  ttsProviders: {},
  comfyuiStatus: null,
  videoProviders: [],
  videoProviderStatus: null,
  videoProviderStatusLoading: false,
  videoProviderStatusError: "",
  scriptPreview: null,
  voicePreview: null,
  reviewFilter: "all",
  reviewTriageState: {
    review_status: "all",
    governance_status: "all",
    provenance: "all",
    deliverable: "all",
    min_rating: 0,
    sort: "scene_order",
  },
  reviewBatchRerender: {
    running: false,
    action: "",
    total: 0,
    completed: 0,
    results: [],
  },
  modal: null,
  assets: {
    characters: [],
    scene_bgs: [],
    props: [],
    activeTab: "character",
    loading: false,
    loadedFor: "",
  },
  styles: {
    list: [],
    loaded: false,
    loading: false,
  },
  busy: false,
  busyText: "",
  projectPollTimer: null,
  fallbackPollTimer: null,
  eventSource: null,
  eventSourceProjectId: "",
  sseConnected: false,
  timelineDrag: null,
  temporalShotDrag: null,
  sfxDrag: null,
  cropEditorSceneOrder: null,
  cropBoxDirty: false,
  toast: null,
  toastTimer: null,
};

export const STORAGE_KEYS = {
  comfyuiBaseUrl: "comicdrama.comfyuiBaseUrl",
};

export const appRoot = document.getElementById("app");
export const voiceCatalogList = document.getElementById("voiceCatalogList");

export let temporalPreviewTimeline = null;
export let temporalPreviewFallbackTimer = null;
export let gsapLoadPromise = null;

export function setTemporalPreviewTimeline(value) {
  temporalPreviewTimeline = value;
}
export function setTemporalPreviewFallbackTimer(value) {
  temporalPreviewFallbackTimer = value;
}
export function setGsapLoadPromise(value) {
  gsapLoadPromise = value;
}

export const assetTabs = [
  ["character", "characters", "角色"],
  ["scene_bg", "scene_bgs", "场景"],
  ["prop", "props", "道具"],
];

export const reviewGovernanceFilterOptions = [
  ["all", "All continuity"],
  ["pass", "Pass"],
  ["warn", "Warn"],
  ["fail", "Fail"],
  ["not_evaluated", "Not evaluated"],
];

export const reviewProvenanceFilterOptions = [
  ["all", "All provenance"],
  ["real", "Real video"],
  ["fallback", "Fallback"],
  ["local", "Local 2.5D"],
  ["unknown", "Unknown"],
];

export const reviewDeliverableFilterOptions = [
  ["all", "All readiness"],
  ["deliverable", "Deliverable"],
  ["blocked", "Blocked"],
  ["asset_gaps", "Missing assets"],
];

export const reviewSortOptions = [
  ["scene_order", "Scene order"],
  ["rating_desc", "Rating high first"],
  ["governance_severity", "Continuity risk"],
  ["fallback_first", "Fallback first"],
];

export const tabs = [
  ["plan", "① 策划", "planSection"],
  ["assets", "② 资产", "assetsSection"],
  ["storyboard", "③ 分镜", "storyboardSection"],
  ["produce", "④ 出片", "produceSection"],
];

export const voiceEngines = [
  ["auto", "自动"],
  ["edge", "Edge TTS"],
  ["local", "本地 pyttsx3"],
  ["cosyvoice", "OmniVoice"],
  ["gpt_sovits", "GPT-SoVITS"],
  ["fish", "Fish Speech"],
  ["indextts", "IndexTTS2"],
  ["silent", "静音"],
];

export const voiceSamples = [
  ["", "无（使用预设）"],
];

export const voiceProfiles = [
  ["", "无"],
  ["male_lead", "男主 · 冷酷主角"],
  ["male_cold", "男冷 · 寡言沉稳"],
  ["male_villain", "男反 · 阴险狡诈"],
  ["male_bully", "男霸 · 嚣张跋扈"],
  ["male_young", "男少 · 少年热血"],
  ["male_narrator", "旁白 · 沉稳叙事"],
  ["female_lead", "女主 · 温柔坚定"],
  ["female_cold", "女冷 · 高冷御姐"],
];

export const voiceEmotions = [
  ["", "默认"],
  ["neutral", "平静"],
  ["cold", "冰冷"],
  ["anger", "愤怒"],
  ["mock", "嘲讽"],
  ["shock", "震惊"],
  ["pain", "痛苦"],
  ["determination", "坚定"],
  ["calm", "沉着"],
  ["joy", "喜悦"],
  ["sadness", "悲伤"],
  ["fear", "恐惧"],
];

export const bgmStyles = [
  ["", "自动匹配"],
  ["tension", "紧张悬疑"],
  ["action", "战斗激烈"],
  ["calm", "平静舒缓"],
  ["sadness", "悲伤忧郁"],
  ["neutral", "中性叙事"],
  ["joy", "欢快明朗"],
  ["fear", "恐惧阴森"],
];

export const bgmFiles = [
  ["", "自动（按风格匹配）"],
  ["assets/audio/bgm/tension/epic_tension.mp3", "史诗紧张"],
  ["assets/audio/bgm/tension/dark_suspense.mp3", "暗黑悬疑"],
  ["assets/audio/bgm/action/battle_action.mp3", "战斗交响"],
  ["assets/audio/bgm/action/martial_arts.mp3", "武侠动作"],
  ["assets/audio/bgm/neutral/cinematic_neutral.mp3", "电影叙事"],
];

export const planners = [
  ["auto", "自动"],
  ["rule", "规则"],
  ["llm", "LLM"],
];

export const cameraOptions = [
  ["dramatic_push", "戏剧推镜"],
  ["melancholy_pan", "情绪横移"],
  ["establishing_tilt", "纵向升降"],
  ["slow_push_in", "慢推进"],
  ["slow_zoom_out", "慢拉远"],
  ["pan_left", "左移"],
  ["pan_right", "右移"],
  ["tilt_down", "下摇"],
  ["tilt_up", "上摇"],
  ["dramatic_reveal", "揭示"],
];

export const reviewStatusOptions = [
  ["unreviewed", "未审"],
  ["approved", "通过"],
  ["needs_work", "需修改"],
  ["blocked", "阻塞"],
];

export const reviewFilterOptions = [
  ["all", "全部"],
  ...reviewStatusOptions,
];
