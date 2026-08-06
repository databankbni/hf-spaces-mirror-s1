export async function getDefinitionRounds(
  definitionId: number,
  options?: { page?: number; pageSize?: number; status?: string }
): Promise<import('@/src/types/challenge').DefinitionRoundsResponse> {
  const params = new URLSearchParams();
  if (options?.page) params.append('page', options.page.toString());
  if (options?.pageSize) params.append('page_size', options.pageSize.toString());
  if (options?.status) params.append('status', options.status);
  
  const url = `/api/v1/definitions/${definitionId}/rounds${params.toString() ? '?' + params.toString() : ''}`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch definition rounds: ${response.status}`);
  }
  return response.json();
}

export async function getDefinitionSeries(
  definitionId: number
): Promise<import('@/src/types/challenge').DefinitionSeries[]> {
  const response = await fetch(`/api/v1/definitions/${definitionId}/series`);
  if (!response.ok) return [];
  return response.json();
}
