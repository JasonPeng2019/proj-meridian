import translations from './translations.json';

// Display translations do not replace source values, IDs or reviewed mappings.
export const englishText = value => {
  const text = String(value ?? '');
  return translations.values[text] || text;
};
export const englishName = value => englishText(value).replace(/\.pdf$/i, '').replaceAll('_', ' ');
export const translated = value => Boolean(translations.values[String(value ?? '')]);
