export const pathKey = key => String(key || '').split('/').map(encodeURIComponent).join('/');
export const partKey = part => part?.key || (part?.id?.startsWith('BOM:') ? `bom/${part.id.slice(4).replace(/\/part$/, '')}` : part?.id?.split('/')[0]) || '';
export const partURL = (key, tab, params = {}) => `/part/${pathKey(key)}${tab ? `/${tab}` : ''}${Object.keys(params).length ? `?${new URLSearchParams(params)}` : ''}`;
export const imageURL = (key, page = 1, thumb = false) => `/api/parts/${pathKey(key)}/image?page=${page}&thumb=${thumb ? 1 : 0}`;
export async function api(url, body) {
  const res = await fetch(url, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let data;
  try { data = await res.json(); } catch { throw new Error(`Request failed (${res.status}). Please check that Meridian is running.`); }
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.message || `Request failed (${res.status})`);
  return data;
}
export const textValue = value => value === null || value === undefined ? 'Not recorded' : typeof value === 'object' ? JSON.stringify(value) : String(value);
export const titleCase = value => String(value || '').replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
export const reviewURL = (id, category = 'needs-input') => `/review/${category}/${pathKey(id)}`;
