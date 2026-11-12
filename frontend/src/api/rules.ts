import { request } from './client';
import type { ParseRule, ReparseResult, TrialResult, UpgradeBatch, UpgradePreview } from '../types/models';

export function listRules(): Promise<ParseRule[]> {
  return request<ParseRule[]>('/rules');
}

export function trial(version: string): Promise<TrialResult> {
  return request<TrialResult>(`/rules/${version}/trial`);
}

/** 同版本重跑；跨版本切换走 upgrade（后端会 409 拦截直接换版本重跑）。 */
export function reparse(version: string): Promise<ReparseResult> {
  return request<ReparseResult>(`/rules/${version}/reparse`, { method: 'POST' });
}

export function upgradePreview(version: string): Promise<UpgradePreview> {
  return request<UpgradePreview>(`/rules/${version}/upgrade/preview`);
}

export function upgrade(version: string): Promise<UpgradeBatch> {
  return request<UpgradeBatch>(`/rules/${version}/upgrade`, { method: 'POST' });
}

export function listUpgrades(): Promise<UpgradeBatch[]> {
  return request<UpgradeBatch[]>('/rules/upgrades');
}

export function activate(version: string): Promise<{ version: string; active: boolean; rules: number }> {
  return request(`/rules/${version}/activate`, { method: 'POST' });
}

export function titleMerge(): Promise<{ merged_count: number; threshold: number; clusters: unknown[] }> {
  return request('/rules/title-merge');
}
