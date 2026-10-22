// Heng 衡 — component props (documentation; window.Heng)
type Tone = 'signal' | 'coral' | 'teal' | 'amber' | 'danger' | 'neutral';

export interface ButtonProps { variant?: 'primary' | 'quiet' | 'ghost'; size?: 'sm' | 'md' | 'lg'; icon?: string; loading?: boolean; disabled?: boolean; onClick?: (e: any) => void; children?: any; }
export interface BadgeProps { tone?: Tone; pulse?: boolean; dot?: boolean; children?: any; }
export interface TabsProps { items: { key: string; label: string }[]; value: string; onChange?: (key: string) => void; }
export interface CountUpProps { value: number; decimals?: number; prefix?: string; suffix?: string; duration?: number; delay?: number; }
export interface SparklineProps { data: number[]; tone?: Tone; width?: number | string; height?: number; }
export interface MetricCardProps { label: string; value: number; decimals?: number; prefix?: string; suffix?: string; delta?: number; deltaDecimals?: number; deltaSuffix?: string; data?: number[]; tone?: Tone; hint?: string; index?: number; }
export interface ScoreRingProps { value: number; label?: string; tone?: Tone; size?: number; stroke?: number; decimals?: number; delay?: number; }
export interface LeaderboardRow { model: string; org: string; delta?: number; scores: Record<string, number>; }
export interface LeaderboardProps { rows: LeaderboardRow[]; metrics?: { key: string; label: string }[]; max?: number; rowHeight?: number; }
export interface RadarProps { axes: string[]; series: { name: string; values: number[]; tone?: Tone }[]; size?: number; label?: string; }
export interface RunJob { name: string; model: string; suite: string; done: number; total: number; status: 'running' | 'queued' | 'done' | 'failed'; }
export interface RunProgressProps { jobs: RunJob[]; simulate?: boolean; tasks?: string[]; }
export interface ArenaCompareProps { prompt: string; a: { model: string; text: string; latency?: string }; b: { model: string; text: string; latency?: string }; verdict?: { a: number; b: number; reason?: string }; judge?: string; }
export interface DashboardProps {}
