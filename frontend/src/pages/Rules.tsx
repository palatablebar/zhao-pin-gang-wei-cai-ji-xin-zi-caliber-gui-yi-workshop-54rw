import { useState } from 'react';
import { activate, listRules, listUpgrades, reparse, titleMerge, trial, upgrade, upgradePreview } from '../api/rules';
import { useAsync } from '../hooks/useAsync';
import { useAuthStore } from '../stores/authStore';
import { can } from '../constants/roles';
import type { ReparseResult, TrialResult, UpgradeBatch, UpgradePreview } from '../types/models';
import { SectionHead } from '../components/common/SectionHead';
import { LoadingBlock } from '../components/common/LoadingBlock';
import { ErrorBlock } from '../components/common/ErrorBlock';
import { MetricCard } from '../components/common/MetricCard';
import { StatusPill } from '../components/common/StatusPill';
import { kYuan } from '../utils/format';
import { errorMessage } from '../utils/errorMessage';

const VERSIONS = ['v1', 'v2'];

export function RulesPage() {
  const user = useAuthStore((state) => state.user);
  const { data, loading, error, reload } = useAsync(listRules, []);
  const upgrades = useAsync(listUpgrades, []);
  const [trials, setTrials] = useState<Record<string, TrialResult>>({});
  const [reparseResult, setReparseResult] = useState<ReparseResult | null>(null);
  const [preview, setPreview] = useState<UpgradePreview | null>(null);
  const [upgradeResult, setUpgradeResult] = useState<UpgradeBatch | null>(null);
  const [mergeInfo, setMergeInfo] = useState<string>('');
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [err, setErr] = useState('');

  const rules = data || [];
  const activeVersion = rules.find((rule) => rule.is_active_set)?.version || 'v1';

  async function runTrial(version: string) {
    setBusy(`trial-${version}`);
    setErr('');
    try {
      const result = await trial(version);
      setTrials((prev) => ({ ...prev, [version]: result }));
    } catch (error_) {
      setErr(errorMessage(error_));
    } finally {
      setBusy('');
    }
  }

  async function runReparse(version: string) {
    setBusy(`reparse-${version}`);
    setErr('');
    setNotice('');
    try {
      const result = await reparse(version);
      setReparseResult(result);
      setNotice(`已按规则 ${version} 重跑 ${result.updated_raws} 条原始岗位，更新 ${result.updated_postings} 条标准化结果`);
      reload();
    } catch (error_) {
      setErr(errorMessage(error_));
    } finally {
      setBusy('');
    }
  }

  async function runPreview(version: string) {
    setBusy(`preview-${version}`);
    setErr('');
    setNotice('');
    setUpgradeResult(null);
    try {
      const result = await upgradePreview(version);
      setPreview(result);
    } catch (error_) {
      setErr(errorMessage(error_));
    } finally {
      setBusy('');
    }
  }

  async function runUpgrade(version: string) {
    setBusy(`upgrade-${version}`);
    setErr('');
    setNotice('');
    try {
      const result = await upgrade(version);
      setUpgradeResult(result);
      setPreview(null);
      setNotice(
        result.idempotent
          ? `规则 ${version} 已升级过（批次 #${result.id}），本次为幂等回放：未新增批次、未抬高报告版本`
          : `批次 #${result.id} 已完成：更新岗位 ${result.updated_postings} 条，保留人工修正 ${result.skipped_corrected} 条，旧报告标记待复核 ${result.benchmarks_marked} 份，新建报告 ${result.reports_created} 份`,
      );
      reload();
      upgrades.reload();
    } catch (error_) {
      setErr(errorMessage(error_));
    } finally {
      setBusy('');
    }
  }

  async function runActivate(version: string) {
    setBusy(`activate-${version}`);
    setErr('');
    try {
      await activate(version);
      setNotice(`规则版本 ${version} 已设为激活口径（admin）`);
      reload();
    } catch (error_) {
      setErr(errorMessage(error_));
    } finally {
      setBusy('');
    }
  }

  async function runMerge() {
    setBusy('merge');
    try {
      const result = await titleMerge();
      setMergeInfo(`3-gram Jaccard ≥ ${result.threshold} 归并演示：${result.merged_count} 条写法归入已有 canonical（${result.clusters.length} 个簇）`);
    } catch (error_) {
      setErr(errorMessage(error_));
    } finally {
      setBusy('');
    }
  }

  return (
    <div className="drawer-in">
      <SectionHead
        eyebrow="04 / RULE VERSIONS"
        title="口径规则管理 · 版本化试跑"
        aside={
          <>
            <span className="tag tag-indigo">激活版本 {activeVersion}</span>
            <button className="btn btn-sm" data-testid="title-merge" onClick={runMerge} disabled={!can(user?.role, 'rule:trial') || busy === 'merge'}>
              标题 3-gram 归并演示
            </button>
          </>
        }
      />
      {loading ? <LoadingBlock /> : null}
      {error ? <ErrorBlock message={error} onRetry={reload} /> : null}
      {err ? <p style={{ color: 'var(--rust)', fontSize: 'var(--fs-small)' }}>{err}</p> : null}
      {notice ? <p style={{ color: 'var(--sage)', fontSize: 'var(--fs-small)' }}>{notice}</p> : null}
      {mergeInfo ? <p style={{ color: 'var(--ink-soft)', fontSize: 'var(--fs-small)' }}>{mergeInfo}</p> : null}

      {preview ? (
        <div className="card drawer-in" style={{ padding: '1rem 1.2rem', marginBottom: '1rem', borderColor: 'var(--copper)' }} data-testid="upgrade-preview">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '1rem' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-micro)', letterSpacing: '0.14em', color: 'var(--copper)' }}>
              UPGRADE PREVIEW · {preview.active_version} → {preview.target_version}
            </div>
            <button className="btn btn-sm" data-testid="upgrade-cancel" onClick={() => setPreview(null)}>取消</button>
          </div>

          {preview.already_applied ? (
            <p style={{ color: 'var(--ink-soft)', fontSize: 'var(--fs-small)', marginTop: '0.5rem' }}>
              批次 #{preview.existing_batch?.id} 已记录本次升级；再次执行只会幂等回放，不会新增批次或抬高报告版本。
            </p>
          ) : null}

          <div className="grid" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', margin: '0.8rem 0' }}>
            <MetricCard label="受影响岗位" value={String(preview.affected_totals.postings)} hint="条（含人工修正保留）" tone="indigo" />
            <MetricCard label="解析结果变化" value={String(preview.affected_totals.changed)} hint="条" tone="copper" />
            <MetricCard label="人工修正保留" value={String(preview.affected_totals.kept_corrected)} hint="条不覆盖" tone="sage" />
            <MetricCard label="已发布报告" value={String(preview.published_reports.length)} hint="份（升级后待复核）" tone="copper" />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.25fr 1fr', gap: '1rem' }}>
            <div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-micro)', letterSpacing: '0.12em', color: 'var(--ink-soft)', marginBottom: '0.35rem' }}>
                受影响岗位（切换前 → 切换后）
              </div>
              <table className="table">
                <thead>
                  <tr><th>岗位</th><th>原薪资</th><th>切换后</th><th>状态</th></tr>
                </thead>
                <tbody>
                  {preview.affected_postings.slice(0, 8).map((row) => (
                    <tr key={row.posting_id} style={{ cursor: 'default' }}>
                      <td>
                        <div style={{ fontWeight: 550 }}>{row.title}</div>
                        <div className="mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-soft)' }}>{row.raw_title} · {row.salary_raw}</div>
                      </td>
                      <td className="mono">{row.salary_median === null ? '—' : kYuan(row.salary_median)}</td>
                      <td className="mono">
                        {row.kept_corrected
                          ? '保留人工修正'
                          : row.after?.salary_median == null
                            ? '—'
                            : kYuan(row.after.salary_median)}
                      </td>
                      <td>
                        {row.kept_corrected
                          ? <span className="tag tag-indigo">人工修正保留</span>
                          : <span className="tag">{row.raw_status} → {row.after?.raw_status}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.affected_postings.length > 8 ? (
                <div className="mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-soft)' }}>
                  仅展示前 8 条，共 {preview.affected_postings.length} 条；完整清单随批次落库可追溯。
                </div>
              ) : null}
            </div>

            <div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-micro)', letterSpacing: '0.12em', color: 'var(--ink-soft)', marginBottom: '0.35rem' }}>
                已发布报告（升级后仍可查看，标待复核）
              </div>
              <table className="table">
                <thead>
                  <tr><th>报告</th><th>规则</th><th>P50</th><th>状态</th></tr>
                </thead>
                <tbody>
                  {preview.reports_to_mark.map((row) => (
                    <tr key={row.id} style={{ cursor: 'default' }}>
                      <td>{row.city} · {row.function_label}</td>
                      <td className="mono">{row.rule_version} · v{row.version}</td>
                      <td className="mono">{kYuan(row.p50)}</td>
                      <td>
                        <StatusPill
                          status={row.published ? 'pending_review' : 'draft'}
                          label={row.published ? '已发布 → 待复核' : '草稿 → 待复核'}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-micro)', letterSpacing: '0.12em', color: 'var(--ink-soft)', margin: '0.7rem 0 0.35rem' }}>
                新报告（仅新规则下有效岗位）
              </div>
              <div style={{ display: 'flex', gap: '0.3rem', flexWrap: 'wrap' }}>
                {preview.reports_to_generate.map((row) => (
                  <span key={`${row.city}-${row.function_type}`} className="tag tag-sage">{row.city} · {row.function_label}</span>
                ))}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '0.9rem' }}>
            <button
              className="btn btn-sm btn-primary"
              data-testid="upgrade-confirm"
              onClick={() => runUpgrade(preview.target_version)}
              disabled={!can(user?.role, 'rule:activate') || busy === `upgrade-${preview.target_version}`}
              title={can(user?.role, 'rule:activate') ? '执行口径升级（admin）' : '仅数据主管可执行升级'}
            >
              {busy === `upgrade-${preview.target_version}` ? '升级中…' : preview.already_applied ? `幂等回放批次（${preview.target_version}）` : `确认升级到 ${preview.target_version}`}
            </button>
            <span style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-soft)' }}>
              单事务执行：任一步失败整体回滚，不会留下半成品批次或改了一半的岗位/报告。
            </span>
          </div>
        </div>
      ) : null}

      {upgradeResult ? (
        <div className="card drawer-in" style={{ padding: '1rem 1.2rem', marginBottom: '1rem', borderColor: 'var(--indigo)' }} data-testid="upgrade-result">
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-micro)', letterSpacing: '0.14em', color: 'var(--copper)' }}>
            UPGRADE BATCH #{upgradeResult.id} · {upgradeResult.previous_version} → {upgradeResult.target_version}
            {upgradeResult.idempotent ? ' · IDEMPOTENT REPLAY' : ''}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '1.2rem', margin: '0.4rem 0' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '2.4rem', color: 'var(--indigo)' }}>
              {upgradeResult.before_rate?.hit_rate_pct}% → {upgradeResult.after_rate?.hit_rate_pct}%
            </div>
            <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-soft)' }}>
              更新岗位 {upgradeResult.updated_postings} 条 · 保留人工修正 {upgradeResult.skipped_corrected} 条
              <br />
              旧报告标待复核 {upgradeResult.benchmarks_marked} 份 · 新建报告 {upgradeResult.reports_created} 份 · 耗时 {upgradeResult.duration_ms}ms
            </div>
          </div>
          <div className="mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-soft)', wordBreak: 'break-all' }}>
            {upgradeResult.summary}
          </div>
        </div>
      ) : null}

      {reparseResult ? (
        <div className="card drawer-in" style={{ padding: '1rem 1.2rem', marginBottom: '1rem', borderColor: 'var(--copper)' }} data-testid="reparse-result">
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-micro)', letterSpacing: '0.14em', color: 'var(--copper)' }}>
            REPARSE · {reparseResult.previous_version} → {reparseResult.active_version}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '1.2rem', margin: '0.4rem 0' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '2.4rem', color: 'var(--indigo)' }}>
              {reparseResult.before.hit_rate_pct}% → {reparseResult.after.hit_rate_pct}%
            </div>
            <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-soft)' }}>
              命中 {reparseResult.before.hits}/{reparseResult.before.attempts} → {reparseResult.after.hits}/{reparseResult.after.attempts}
              <br />
              更新岗位 {reparseResult.updated_postings} 条 · 跳过人工修正 {reparseResult.skipped_corrected} 条 · 耗时 {reparseResult.duration_ms}ms
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            OK：{Object.entries(reparseResult.after.reason_breakdown).slice(0, 6).map(([reason, count]) => (
              <span key={reason} className="tag">{reason} × {count}</span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
        {VERSIONS.map((version) => {
          const versionRules = rules.filter((rule) => rule.version === version);
          const trialData = trials[version];
          const isActive = version === activeVersion;
          return (
            <section key={version} className="card" style={{ padding: '1rem 1.15rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <h3 style={{ fontSize: '1.3rem' }}>
                  规则集 {version}
                  {version === 'v1' ? <span className="tag" style={{ marginLeft: '0.5rem' }}>历史基线</span> : null}
                  {version === 'v2' ? <span className="tag tag-copper" style={{ marginLeft: '0.5rem' }}>增补口径</span> : null}
                </h3>
                <span className="tag">{versionRules.length} 条规则</span>
              </div>
              {isActive ? <span className="tag tag-sage" style={{ marginBottom: '0.4rem', display: 'inline-block' }}>当前激活口径</span> : null}
              <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', margin: '0.6rem 0' }}>
                <button className="btn btn-sm" data-testid={`trial-${version}`} onClick={() => runTrial(version)} disabled={!can(user?.role, 'rule:trial') || busy === `trial-${version}`}>
                  {busy === `trial-${version}` ? '试跑中…' : '试跑命中率'}
                </button>
                {isActive ? (
                  <button className="btn btn-sm btn-ghost" data-testid={`reparse-${version}`} onClick={() => runReparse(version)} disabled={!can(user?.role, 'rule:reparse') || busy === `reparse-${version}`}>
                    {busy === `reparse-${version}` ? '重跑中…' : `重跑 ${version}（同口径）`}
                  </button>
                ) : (
                  <button className="btn btn-sm btn-primary" data-testid={`upgrade-${version}`} onClick={() => runPreview(version)} disabled={!can(user?.role, 'rule:activate') || busy === `preview-${version}`} title={can(user?.role, 'rule:activate') ? '先预览受影响岗位与已发布报告，再执行升级' : '仅数据主管可执行版本升级'}>
                    {busy === `preview-${version}` ? '读取影响面…' : `升级到 ${version}（先预览）`}
                  </button>
                )}
                <button
                  className="btn btn-sm btn-ghost"
                  data-testid={`activate-${version}`}
                  onClick={() => runActivate(version)}
                  disabled={!can(user?.role, 'rule:activate') || busy === `activate-${version}`}
                  title={can(user?.role, 'rule:activate') ? 'admin 才能激活版本' : '仅数据主管可激活'}
                >
                  仅激活版本
                </button>
              </div>

              {trialData ? (
                <div className="drawer-in" style={{ border: '1px solid var(--paper-line)', padding: '0.65rem 0.75rem', marginBottom: '0.6rem', background: 'var(--paper)' }}>
                  <div style={{ display: 'flex', gap: '1rem', alignItems: 'baseline' }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.9rem', color: 'var(--indigo)' }}>{trialData.hit_rate_pct}%</div>
                    <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-soft)' }}>
                      命中 {trialData.hits} / {trialData.attempts}（{trialData.hit_rate}%）· 未命中 {trialData.misses}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '0.3rem', flexWrap: 'wrap', marginTop: '0.35rem' }}>
                    {Object.entries(trialData.reason_breakdown).map(([reason, count]) => (
                      <span key={reason} className="tag">{reason} × {count}</span>
                    ))}
                  </div>
                  <div style={{ marginTop: '0.4rem', fontSize: 'var(--fs-micro)', color: 'var(--ink-soft)', fontFamily: 'var(--font-mono)' }}>
                    {trialData.samples.slice(0, 4).map((sample) => (
                      <div key={sample.raw}>{sample.raw} → {sample.status} ({sample.reason_code})</div>
                    ))}
                  </div>
                </div>
              ) : null}

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                {versionRules.map((rule) => (
                  <div key={rule.id} style={{ borderTop: '1px dashed var(--paper-line)', paddingTop: '0.35rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}>
                      <span style={{ fontSize: 'var(--fs-small)', fontWeight: 550 }}>{rule.name}</span>
                      <span className="mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-soft)' }}>hit {rule.hit_count}</span>
                    </div>
                    <div className="mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--indigo)', wordBreak: 'break-all' }}>{rule.pattern}</div>
                    <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-soft)' }}>{rule.description}</div>
                  </div>
                ))}
              </div>
            </section>
          );
        })}
      </div>

      <div className="card" style={{ marginTop: '1rem', padding: '0.9rem 1.1rem' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-micro)', letterSpacing: '0.14em', color: 'var(--copper)', marginBottom: '0.4rem' }}>
          UPGRADE HISTORY · 可追踪批次
        </div>
        {upgrades.loading ? <LoadingBlock label="读取批次…" /> : null}
        {!upgrades.loading && (upgrades.data || []).length === 0 ? (
          <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-soft)' }}>还没有口径升级批次；切版本前先预览再执行。</div>
        ) : null}
        <table className="table">
          {(upgrades.data || []).length > 0 ? (
            <thead>
              <tr><th>批次</th><th>版本</th><th>岗位</th><th>人工修正</th><th>旧报告待复核</th><th>新报告</th><th>执行人</th><th>时间</th></tr>
            </thead>
          ) : null}
          <tbody>
            {(upgrades.data || []).map((batch) => (
              <tr key={batch.id} style={{ cursor: 'default' }}>
                <td className="mono">#{batch.id}</td>
                <td className="mono">{batch.previous_version} → {batch.target_version}</td>
                <td className="mono">更新 {batch.updated_postings}</td>
                <td className="mono">保留 {batch.skipped_corrected}</td>
                <td className="mono">{batch.benchmarks_marked}</td>
                <td className="mono">{batch.reports_created}</td>
                <td>{batch.actor_email}</td>
                <td className="mono" style={{ fontSize: 'var(--fs-micro)' }}>{batch.finished_at || batch.started_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ marginTop: '1rem', padding: '0.9rem 1.1rem', fontSize: 'var(--fs-small)', color: 'var(--ink-soft)' }}>
        口径口径：规则命中率 = 成功判定薪资语义（数值区间或明确面议）的条数 ÷ 尝试条数。
        v1 为历史基线（164/180 = 91.1%）；v2 增补面议识别、日结/时薪折算、中文千区间（173/180 = 96.1%）。
        跨版本切换必须走「预览 → 确认升级」：单事务执行、重复执行同一版本幂等回放，已发布旧报告保留并标待复核。
      </div>
    </div>
  );
}
