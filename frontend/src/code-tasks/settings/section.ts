export const codeSettingsSections = [
  { value: 'repositories', label: '仓库' },
  { value: 'execution', label: '执行配置' },
  { value: 'checks', label: '检查配置' },
  { value: 'authorizations', label: '授权' },
] as const;
export type CodeSettingsSection = (typeof codeSettingsSections)[number]['value'];
/** Canonical settings sections, independent of DOM and navigation side effects. */
export function codeSettingsSection(search: string): CodeSettingsSection | null {
  const query = new URLSearchParams(search);
  if ([...query.keys()].some((key) => key !== 'section')) return null;
  const sections = query.getAll('section');
  if (sections.length === 0) return 'repositories';
  if (sections.length !== 1) return null;
  return codeSettingsSections.find((option) => option.value === sections[0])?.value ?? null;
}
