/** Voice clone API 响应类型 */

export interface VoiceCloneResponse {
  voice_id: string;
  audio_url: string;
  duration: number;
}

export interface AudioValidationResult {
  valid: boolean;
  message: string;
}

export interface CloneParams {
  speed: number;
  volume: number;
  pitch: number;
}
