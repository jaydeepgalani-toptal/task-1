export async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`fetch_failed status=${response.status}`);
  }
  return response.json();
}
