/**
 * Meetings API — Video Transcription Service
 * API endpoint: NEXT_PUBLIC_API_BASE_URL (default: http://localhost:8020)
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8020'

// ============================================================================
// Types
// ============================================================================

export type MeetingStatus =
  | 'detected'
  | 'queued'
  | 'processing'
  | 'extracting_audio'
  | 'transcribing'
  | 'diarizing'
  | 'analyzing'
  | 'generating_documents'
  | 'exporting_to_obsidian'
  | 'completed'
  | 'failed'
  | 'partial_completed'

export interface MeetingListItem {
  id: string
  folder_name: string
  status: MeetingStatus
  status_label: string
  created_at: string
  updated_at: string
  title?: string
  duration_sec: number
  source_files_count: number
  language?: string
  speaker_count: number
  task_count: number
  has_transcript: boolean
  has_analysis: boolean
  has_obsidian: boolean
  last_error?: string
}

export interface MeetingListResponse {
  meetings: MeetingListItem[]
  total: number
}

export interface TranscriptSegment {
  start: number
  end: number
  speaker?: string
  text: string
  timecode: string
}

export interface TranscriptResult {
  text: string
  language: string
  segments: TranscriptSegment[]
  duration_sec: number
  audio_duration_sec: number
  has_speakers: boolean
}

export interface AnalysisTask {
  title: string
  description: string
  assignee?: string
  due_date?: string
  priority: 'high' | 'medium' | 'low'
  source_fragment?: string
  speaker?: string
  timecode?: string
}

export interface AnalysisResult {
  meeting_id: string
  title: string
  language: string
  duration_sec: number
  participants: string[]
  summary: string
  key_points: string[]
  decisions: string[]
  open_questions: string[]
  tasks: AnalysisTask[]
  notes_markdown: string
  transcript_segments: TranscriptSegment[]
}

export interface MeetingMeta {
  id: string
  folder_name: string
  folder_path: string
  status: MeetingStatus
  created_at: string
  updated_at: string
  started_at?: string
  finished_at?: string
  source_files: string[]
  audio_extracted: boolean
  transcript_status: string
  diarization_status: string
  analysis_status: string
  documents_status: string
  obsidian_status: string
  audio_path?: string
  transcript_path?: string
  analysis_path?: string
  meeting_note_path?: string
  title?: string
  language?: string
  duration_sec: number
  speaker_count: number
  task_count: number
  last_error?: string
  stage_errors: Record<string, string>
}

export interface MeetingDetail {
  meta: MeetingMeta
  transcript?: TranscriptResult
  analysis?: AnalysisResult
  artifacts: string[]
}

export interface ScanResponse {
  new_meetings: number
  total_detected: number
  folders: string[]
}

export interface WatcherStatus {
  running: boolean
  inbox_path: string
  polling_interval_sec: number
  total_meetings: number
  processing_count: number
  currently_processing: string[]
}

export interface ReprocessRequest {
  from_stage?: string
  force?: boolean
}

// ============================================================================
// API Functions
// ============================================================================

export async function listMeetings(params?: {
  status?: string
  search?: string
  limit?: number
  offset?: number
}): Promise<MeetingListResponse> {
  const url = new URL(`${API_BASE}/api/meetings`)
  if (params?.status) url.searchParams.set('status', params.status)
  if (params?.search) url.searchParams.set('search', params.search)
  if (params?.limit !== undefined) url.searchParams.set('limit', String(params.limit))
  if (params?.offset !== undefined) url.searchParams.set('offset', String(params.offset))

  const resp = await fetch(url.toString(), { cache: 'no-store' })
  if (!resp.ok) throw new Error(`Ошибка загрузки встреч: ${resp.status}`)
  return resp.json()
}

export async function getMeeting(meetingId: string): Promise<MeetingDetail> {
  const resp = await fetch(`${API_BASE}/api/meetings/${meetingId}`, { cache: 'no-store' })
  if (!resp.ok) {
    if (resp.status === 404) throw new Error('Встреча не найдена')
    throw new Error(`Ошибка загрузки встречи: ${resp.status}`)
  }
  return resp.json()
}

export async function reprocessMeeting(
  meetingId: string,
  fromStage: string = 'start'
): Promise<{ success: boolean }> {
  const resp = await fetch(`${API_BASE}/api/meetings/${meetingId}/reprocess`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from_stage: fromStage, force: true }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail || 'Ошибка запуска обработки')
  }
  return resp.json()
}

export async function exportToObsidian(meetingId: string): Promise<{ success: boolean }> {
  const resp = await fetch(`${API_BASE}/api/meetings/${meetingId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ overwrite: true }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail || 'Ошибка экспорта в Obsidian')
  }
  return resp.json()
}

export async function regenerateAnalysis(meetingId: string): Promise<{ success: boolean }> {
  const resp = await fetch(`${API_BASE}/api/meetings/${meetingId}/regenerate-analysis`, {
    method: 'POST',
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail || 'Ошибка перегенерации анализа')
  }
  return resp.json()
}

export async function scanInbox(): Promise<ScanResponse> {
  const resp = await fetch(`${API_BASE}/api/meetings/scan`, { method: 'POST' })
  if (!resp.ok) throw new Error('Ошибка сканирования inbox')
  return resp.json()
}

export async function getWatcherStatus(): Promise<WatcherStatus> {
  const resp = await fetch(`${API_BASE}/api/meetings/status/watcher`, { cache: 'no-store' })
  if (!resp.ok) throw new Error('Ошибка получения статуса watcher')
  return resp.json()
}

export async function listArtifacts(
  meetingId: string
): Promise<{ meeting_id: string; artifacts: string[]; total: number }> {
  const resp = await fetch(`${API_BASE}/api/meetings/${meetingId}/artifacts`, {
    cache: 'no-store',
  })
  if (!resp.ok) throw new Error('Ошибка получения артефактов')
  return resp.json()
}

// ============================================================================
// Helpers
// ============================================================================

export function formatDuration(sec: number): string {
  const total = Math.floor(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

export function statusColor(status: MeetingStatus): string {
  const map: Record<string, string> = {
    detected: 'text-muted-foreground',
    queued: 'text-blue-500',
    processing: 'text-yellow-500',
    extracting_audio: 'text-yellow-500',
    transcribing: 'text-yellow-500',
    diarizing: 'text-yellow-500',
    analyzing: 'text-yellow-500',
    generating_documents: 'text-yellow-500',
    exporting_to_obsidian: 'text-yellow-500',
    completed: 'text-green-500',
    partial_completed: 'text-orange-500',
    failed: 'text-red-500',
  }
  return map[status] ?? 'text-muted-foreground'
}

export function isProcessing(status: MeetingStatus): boolean {
  return ![
    'completed',
    'partial_completed',
    'failed',
    'detected',
    'queued',
  ].includes(status)
}
