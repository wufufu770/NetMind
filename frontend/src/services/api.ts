export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export async function api<T>(path:string, init?:RequestInit):Promise<T>{ const r=await fetch(API_URL+path, init); if(!r.ok) throw new Error(await r.text()); return r.json(); }
