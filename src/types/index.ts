// VoiceClonePage — 共享类型与常量
// 参考: design/V1.0-Design-VoiceClonePage.md §4.1

// ── API 请求/响应 ──

export interface VoiceCloneRequest {
  voice_id: string;
  audio_sample: File | Blob;
  audio_prompt?: File | Blob;
  trial_text: string;
}

export interface VoiceCloneResponse {
  voice_id: string;
  audio_url: string;
  speed: number;
  volume: number;
  pitch: number;
}

// ── 校验结果 ──

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

// ── 克隆阶段 ──

export type ClonePhase = 'idle' | 'validating' | 'uploading' | 'cloning' | 'done' | 'error';

export interface CloneState {
  phase: ClonePhase;
  progress: number;
  result: VoiceCloneResponse | null;
  error: string | null;
}

// ── 录音状态 ──

export interface RecordingState {
  isRecording: boolean;
  duration: number;
  audioBlob: Blob | null;
  error: string | null;
}

// ── 音频约束常量 ──

export const AUDIO_CONSTRAINTS = {
  minDuration: 10,
  maxDuration: 300,
  maxSize: 20 * 1024 * 1024,
  allowedFormats: ['audio/mp3', 'audio/mp4', 'audio/x-m4a', 'audio/wav', 'audio/x-wav'],
} as const;

// ── Voice ID 约束 ──

export const VOICE_ID_RULES = {
  minLength: 8,
  maxLength: 256,
} as const;
