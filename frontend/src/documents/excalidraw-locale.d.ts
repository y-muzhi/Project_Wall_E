// The 0.18.1 package ships locale scripts, but its i18n declaration still
// imports the unpublished English JSON to derive translation key names.
declare module '*/locales/en.json' {
  const locale: Record<string, string>;
  export default locale;
}
