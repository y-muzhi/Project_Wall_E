import { useState } from 'react';
import type { ReactNode } from 'react';
import type { CheckSetVersion } from '../../api/code-check-sets.ts';
import type { ExecutionProfileVersion } from '../../api/code-execution-profiles.ts';
import { EmptyState } from '../../shared/empty-state.tsx';

type Version = ExecutionProfileVersion | CheckSetVersion;
type Fact = readonly [label: string, value: ReactNode];
const stageLabels = { BACKEND: '后端', FRONTEND: '前端', INTEGRATION: '联调', ACCEPTANCE: '验收' };
const coverageLabels = { AUTO: '自动', MANUAL: '人工', NOT_APPLICABLE: '不适用' };

function refs(values: readonly string[]) {
  return values.length ? values.join('、') : '未配置';
}
function stages(values: readonly (keyof typeof stageLabels)[]) {
  return values.map((value) => stageLabels[value]).join('、');
}
function Facts({ rows }: { rows: readonly Fact[] }) {
  return (
    <dl className="code-settings-resource-facts">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
function ProfileDetails({ version }: { version: ExecutionProfileVersion }) {
  return (
    <>
      <Facts
        rows={[
          ['执行器', version.executor.version + ' · ' + version.executor.binary_ref],
          ['执行器运行包', version.executor.runtime_bundle_ref],
          ['Git', version.git.version + ' · ' + version.git.binary_ref],
          ['Git 运行包', version.git.runtime_bundle_ref],
          ['Python', version.environment.python_ref ?? '未配置'],
          ['Node.js', version.environment.node_ref ?? '未配置'],
          ['包管理器', refs(version.environment.package_manager_refs)],
          ['检查集版本 ID', version.check_set_version_id],
          ['产品捕获范围', refs(version.capture_rules.product_include_paths)],
          ['非产品排除范围', refs(version.capture_rules.nonproduct_exclude_paths)],
          ['模型请求上限', version.limits.max_model_requests + ' 次'],
          ['单次输出上限', version.limits.max_output_tokens + ' Token'],
          ['运行时长上限', version.limits.max_active_seconds + ' 秒'],
        ]}
      />
      <h4>模型绑定</h4>
      <ul>
        {version.models.bindings.map((binding) => (
          <li key={binding.native_model_id}>
            <strong>{binding.purpose === 'CODE' ? '代码执行' : '上下文压缩'}</strong>
            <Facts
              rows={[
                ['模型配置', binding.model_profile_ref],
                ['模型快照', binding.model_snapshot_ref],
                ['计价版本 ID', binding.price_version_id],
                [
                  '输入／上下文／输出上限',
                  [
                    binding.input_cap_tokens,
                    binding.context_cap_tokens,
                    binding.output_cap_tokens,
                  ].join(' / ') + ' Token',
                ],
              ]}
            />
          </li>
        ))}
      </ul>
      <h4>登记命令</h4>
      {version.commands.length === 0 ? (
        <EmptyState icon="history" message="此版本未配置登记命令" compact />
      ) : (
        <ul>
          {version.commands.map((command) => (
            <li key={command.command_id}>
              <strong>{command.command_id}</strong>
              <Facts
                rows={[
                  ['执行程序', command.executable_ref],
                  ['工作目录', command.working_directory],
                  ['时限', command.timeout_seconds + ' 秒'],
                  ['网络范围', command.network_scope_ref ?? '未配置'],
                ]}
              />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
function CheckDetails({ version }: { version: CheckSetVersion }) {
  return (
    <>
      <Facts rows={[['所属模块', version.owner_module === 'CODING' ? '代码开发' : '测试验收']]} />
      <h4>检查项</h4>
      {version.items.length === 0 ? (
        <EmptyState icon="history" message="此版本未配置检查项" compact />
      ) : (
        <ul>
          {version.items.map((check) => (
            <li key={check.check_id}>
              <strong>
                {check.name} · {check.check_id}
              </strong>
              <Facts
                rows={[
                  ['检查阶段', stages(check.stages)],
                  ['要求', check.required ? '必检' : '非必检'],
                  ['类型', check.check_kind === 'PROJECT_COMMAND' ? '项目命令' : '受控断言'],
                  ['运行器', check.runner_ref],
                  ['命令', check.command_id ?? '未配置'],
                  ['用例包', check.case_pack_ref ?? '未配置'],
                  ['时限', check.timeout_seconds + ' 秒'],
                ]}
              />
            </li>
          ))}
        </ul>
      )}
      <h4>覆盖方案</h4>
      {version.coverage_plan.length === 0 ? (
        <EmptyState icon="history" message="此版本未配置覆盖方案" compact />
      ) : (
        <ul>
          {version.coverage_plan.map((coverage) => (
            <li key={coverage.coverage_id}>
              <strong>
                {coverage.coverage_id} · {coverageLabels[coverage.mode]}
              </strong>
              <p>{stages(coverage.stages)}</p>
              {coverage.check_ids.length > 0 && <p>检查项　{refs(coverage.check_ids)}</p>}
              {coverage.explanation && <p>{coverage.explanation}</p>}
              {coverage.basis_refs.map((basis) => (
                <figure key={JSON.stringify([basis.document_id, basis.revision_id, basis.quote])}>
                  <figcaption>
                    文档 #{basis.document_id} · 修订 #{basis.revision_id}
                  </figcaption>
                  <blockquote>{basis.quote}</blockquote>
                </figure>
              ))}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function ConfigurationVersionDetails({ version }: { version: Version }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="code-settings-version-details"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>版本 {version.version} 详情</summary>
      {open &&
        ('profile_id' in version ? (
          <ProfileDetails version={version} />
        ) : (
          <CheckDetails version={version} />
        ))}
    </details>
  );
}
