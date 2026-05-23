export type ProjectStatus = "draft" | "active" | "archived";

export type ProjectType = {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
};

export type Project = {
  id: number;
  name: string;
  description: string | null;
  status: ProjectStatus;
  project_type: ProjectType;
  created_at: string;
  updated_at: string;
};

export type CapabilityLevel = 1 | 2 | 3;

export type Capability = {
  id: number;
  project_id: number;
  parent_id: number | null;
  level: CapabilityLevel;
  name: string;
  description: string | null;
  position: number;
  created_at: string;
  updated_at: string;
};

export type ChatRole = "user" | "assistant";

export type Citation = {
  url: string;
  title: string;
  cited_text?: string | null;
};

export type ChatMessage = {
  id: number;
  role: ChatRole;
  content: string;
  thinking?: string | null;
  citations?: Citation[];
  model_provider: string | null;
  model_id: string | null;
  created_at: string;
};

export type ChatThread = {
  id: number;
  project_id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ProjectFileKind = "pdf" | "image";

export type ProjectFile = {
  id: number;
  project_id: number;
  anthropic_file_id: string;
  original_filename: string;
  kind: ProjectFileKind;
  mime_type: string;
  size_bytes: number;
  uploaded_at: string;
};

export type DataQualitySheetSummary = {
  name: string;
  row_count: number;
  column_count: number;
};

export type DataQualityDataset = {
  id: number;
  project_id: number;
  original_filename: string;
  file_sha256: string;
  size_bytes: number;
  sheets: DataQualitySheetSummary[];
  engine_version: string;
  uploaded_at: string;
  profiled_at: string | null;
  annotation_status: "pending" | "running" | "done" | "failed";
  annotation_error: string | null;
  annotated_at: string | null;
  // Epic 3: similarity-config completion gate. NULL when the user has not
  // yet visited or skipped the Profiling Setup & Configuration page; the
  // DataQualitySection mounts the config page until this is set.
  config_completed_at: string | null;
};

export type DqRag = "green" | "amber" | "red";
export type DqSeverity = "low" | "medium" | "high" | "critical";
export type DqDimension =
  | "completeness"
  | "consistency"
  | "uniqueness"
  | "validity"
  | "accuracy"
  | "redundancy";
export type DqAiStatus = "pending" | "running" | "done" | "failed";
export type DqRelationshipStatus = "suggested" | "confirmed" | "dismissed";
export type DqCardinality = "one_to_one" | "many_to_one" | "unknown";

export type DqTopValue = { value: string; count: number };

export type DqColumnProfile = {
  id: number;
  name: string;
  ordinal: number;
  inferred_dtype: string;
  semantic_type: string;
  type_mismatch_count: number;
  null_count: number;
  null_pct: number;
  distinct_count: number;
  distinct_pct: number;
  top_values: DqTopValue[];
  numeric_min: number | null;
  numeric_max: number | null;
  numeric_mean: number | null;
  numeric_median: number | null;
  numeric_std: number | null;
  numeric_p25: number | null;
  numeric_p75: number | null;
  date_min: string | null;
  date_max: string | null;
  pattern_label: string | null;
  pattern_conformance_pct: number | null;
  outlier_iqr_count: number | null;
  outlier_mad_count: number | null;
  range_min: number | null;
  range_max: number | null;
  range_violation_count: number | null;
  rag: DqRag;
  computed_at: string;
};

export type DqSheetProfile = {
  id: number;
  sheet_name: string;
  row_count: number;
  column_count: number;
  exact_duplicate_row_count: number;
  completeness_pct: number;
  rag: DqRag;
  engine_version: string;
  computed_at: string;
  columns: DqColumnProfile[];
};

export type DqIssue = {
  id: number;
  sheet_name: string;
  column_name: string | null;
  dimension: DqDimension;
  severity: DqSeverity;
  description: string;
  sample_value_count: number;
  sample_values: string[];
  engine_version: string;
  ai_narrative: string | null;
  ai_fix: string | null;
  ai_status: DqAiStatus;
  created_at: string;
};

export type DqFunctionalDependency = {
  id: number;
  sheet_name: string;
  determinant_column: string;
  dependent_column: string;
  confidence_pct: number;
  counter_example_count: number;
  sample_counter_examples: string[];
  engine_version: string;
  computed_at: string;
};

export type DqRelationship = {
  id: number;
  parent_sheet: string;
  parent_column: string;
  child_sheet: string;
  child_column: string;
  type_match: boolean;
  name_similarity: number;
  subset_coverage: number;
  cardinality: DqCardinality;
  confidence_pct: number;
  status: DqRelationshipStatus;
  engine_version: string;
  suggested_at: string;
  confirmed_at: string | null;
  dismissed_at: string | null;
};

export type LlmProvider = "anthropic" | "openai";

export type LlmKeysStatus = {
  provider: LlmProvider | null;
  llm_configured: boolean;
  model: string | null;
  available_models: string[];
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type StreamEvent =
  | { type: "user_message"; data: ChatMessage }
  | { type: "text_delta"; data: { text: string } }
  | { type: "thinking_delta"; data: { text: string } }
  | { type: "tool_call"; data: { id: string; name: string; input: Record<string, unknown> } }
  | { type: "tool_result"; data: { tool_use_id: string; is_error: boolean; preview: string } }
  | { type: "assistant_message"; data: ChatMessage }
  | { type: "error"; data: { message: string } }
  | { type: "done"; data: Record<string, never> };

export async function streamChat(
  projectId: number,
  content: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
  opts?: { fileIds?: number[]; threadId?: number },
): Promise<void> {
  const r = await fetch(`/api/projects/${projectId}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      content,
      file_ids: opts?.fileIds ?? null,
      thread_id: opts?.threadId ?? null,
    }),
    signal,
  });

  if (r.status === 401 && typeof window !== "undefined") {
    window.location.href = "/login";
    throw new ApiError(401, "Not authenticated");
  }
  if (!r.ok) {
    let message = `HTTP ${r.status}`;
    try {
      const body = (await r.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      /* ignore parse */
    }
    throw new ApiError(r.status, message);
  }
  if (!r.body) {
    throw new ApiError(500, "Streaming response has no body");
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseFrame(raw);
      if (parsed) onEvent(parsed);
      boundary = buffer.indexOf("\n\n");
    }
  }

  if (buffer.trim()) {
    const parsed = parseSseFrame(buffer);
    if (parsed) onEvent(parsed);
  }
}

export async function streamDqChat(
  projectId: number,
  datasetId: number,
  content: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(
    `/api/projects/${projectId}/dq/datasets/${datasetId}/chat/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ content }),
      signal,
    },
  );

  if (r.status === 401 && typeof window !== "undefined") {
    window.location.href = "/login";
    throw new ApiError(401, "Not authenticated");
  }
  if (!r.ok) {
    let message = `HTTP ${r.status}`;
    try {
      const body = (await r.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      /* ignore parse */
    }
    throw new ApiError(r.status, message);
  }
  if (!r.body) throw new ApiError(500, "Streaming response has no body");

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseFrame(raw);
      if (parsed) onEvent(parsed);
      boundary = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) {
    const parsed = parseSseFrame(buffer);
    if (parsed) onEvent(parsed);
  }
}

function parseSseFrame(raw: string): StreamEvent | null {
  let type: string | null = null;
  let data: unknown = null;
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      type = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      try {
        data = JSON.parse(line.slice(5).trim());
      } catch {
        data = null;
      }
    }
  }
  if (!type) return null;
  return { type, data: (data ?? {}) as never } as StreamEvent;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (r.status === 401 && typeof window !== "undefined") {
    window.location.href = "/login";
    throw new ApiError(401, "Not authenticated");
  }

  if (!r.ok) {
    let message = `HTTP ${r.status}`;
    try {
      const body = (await r.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // ignore body parse errors
    }
    throw new ApiError(r.status, message);
  }

  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

// ---------------------------------------------------------------------------
// Epic 3 — Record-Level Similarity Scoring
// ---------------------------------------------------------------------------

export type DqAlgorithm =
  | "exact"
  | "levenshtein"
  | "jaro_winkler"
  | "jaccard_tokens"
  | "cosine_tokens"
  | "soundex"
  | "metaphone"
  | "ngram"
  | "numeric_tolerance"
  | "date_proximity";

export type DqParser = "phone" | "email" | "date";
export type DqRecommendedBy = "heuristic" | "llm" | "user";
export type DqRunStatus = "running" | "done" | "failed";

export type DqColumnMapping = {
  id?: number;
  column_a: string;
  column_b: string;
  algorithm: DqAlgorithm;
  weight: number;
  is_important: boolean;
  parser: DqParser | null;
  recommended_by: DqRecommendedBy;
};

export type DqProfileConfig = {
  id: number;
  sheet_a: string | null;
  sheet_b: string | null;
  normalization: Record<string, boolean>;
  threshold: number;
  engine_version: string;
  created_at: string;
  updated_at: string;
  mappings: DqColumnMapping[];
};

export type DqConfigDraft = {
  saved: false;
  available_sheets: string[];
  suggested_sheet_a: string | null;
  suggested_sheet_b: string | null;
  normalization: Record<string, boolean>;
  threshold: number;
  mappings: DqColumnMapping[];
};

// Discriminator: saved configs carry an `id`; drafts carry `saved: false`.
export type DqConfigOrDraft = DqProfileConfig | DqConfigDraft;

export function isDqConfigSaved(
  c: DqConfigOrDraft,
): c is DqProfileConfig {
  return (c as { saved?: boolean }).saved !== false;
}

export type DqRecommendation = {
  normalization: Record<string, boolean>;
  threshold: number;
  mappings: DqColumnMapping[];
  llm_error: string | null;
};

export type DqSimilarityRun = {
  id: number;
  dataset_id: number;
  config_id: number;
  sheet_a: string;
  sheet_b: string;
  threshold: number;
  status: DqRunStatus;
  candidate_pair_count: number;
  passing_pair_count: number;
  cluster_count: number;
  blocking_column: string | null;
  error: string | null;
  engine_version: string;
  started_at: string;
  finished_at: string | null;
};

export type DqRecordCluster = {
  id: number;
  run_id: number;
  cluster_index: number;
  a_member_count: number;
  b_member_count: number;
  top_score: number;
  min_score: number;
  canonical_key: Record<string, string | number | null>;
  a_members: number[];
  b_members: number[];
};

export type DqRecordPair = {
  id: number;
  cluster_id: number | null;
  row_a_index: number;
  row_b_index: number;
  score: number;
  per_column_scores: Record<string, number>;
};

export type DqClusterDetail = {
  cluster: DqRecordCluster;
  pairs: DqRecordPair[];
  a_rows: Array<Record<string, string | number | null>>;
  b_rows: Array<Record<string, string | number | null>>;
};

// ---------------------------------------------------------------------------
// IT Map Agent
// ---------------------------------------------------------------------------

export type ItMapRunStatus = "running" | "done" | "failed";
export type ItMapMappingStatus = "suggested" | "confirmed" | "dismissed";

export type ItMapInventorySheet = {
  name: string;
  row_count: number;
  column_count: number;
};

export type ItMapInventory = {
  id: number;
  project_id: number;
  original_filename: string;
  file_sha256: string;
  size_bytes: number;
  sheets: ItMapInventorySheet[];
  primary_sheet: string;
  engine_version: string;
  uploaded_at: string;
};

export type ItMapAgentRun = {
  id: number;
  inventory_id: number;
  status: ItMapRunStatus;
  tool_call_count: number;
  application_count: number;
  mapping_count: number;
  unmappable_count: number;
  error: string | null;
  engine_version: string;
  started_at: string;
  finished_at: string | null;
};

export type ItMapMapping = {
  id: number;
  capability_id: number;
  confidence: number;
  rationale: string;
  status: ItMapMappingStatus;
  engine_version: string;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
  dismissed_at: string | null;
};

export type ItMapApplication = {
  id: number;
  inventory_id: number;
  sheet_name: string;
  row_index: number;
  raw_row: Record<string, string | number | boolean | null>;
  inferred_name: string | null;
  inferred_description: string | null;
  inferred_business_function: string | null;
  inferred_technology: string | null;
  inferred_owner: string | null;
  inferred_criticality: string | null;
  inferred_lifecycle: string | null;
  unmappable_reason: string | null;
  created_at: string;
  mappings: ItMapMapping[];
};

export const api = {
  listProjectTypes: () => request<ProjectType[]>("/api/project-types"),

  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (body: {
    name: string;
    description?: string | null;
    project_type_code: string;
  }) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateProject: (
    id: number,
    body: Partial<{
      name: string;
      description: string | null;
      status: ProjectStatus;
    }>,
  ) =>
    request<Project>(`/api/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteProject: (id: number) =>
    request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  listCapabilities: (projectId: number) =>
    request<Capability[]>(`/api/projects/${projectId}/capabilities`),
  createCapability: (
    projectId: number,
    body: {
      name: string;
      description?: string | null;
      level: CapabilityLevel;
      parent_id?: number | null;
      position?: number;
    },
  ) =>
    request<Capability>(`/api/projects/${projectId}/capabilities`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateCapability: (
    projectId: number,
    capId: number,
    body: Partial<{
      name: string;
      description: string | null;
      parent_id: number | null;
      position: number;
    }>,
  ) =>
    request<Capability>(`/api/projects/${projectId}/capabilities/${capId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteCapability: (projectId: number, capId: number) =>
    request<void>(`/api/projects/${projectId}/capabilities/${capId}`, {
      method: "DELETE",
    }),

  listChat: (projectId: number, threadId?: number) =>
    request<ChatMessage[]>(
      `/api/projects/${projectId}/chat${threadId ? `?thread_id=${threadId}` : ""}`,
    ),
  postChat: (
    projectId: number,
    content: string,
    opts?: { file_ids?: number[]; thread_id?: number },
  ) =>
    request<ChatMessage[]>(`/api/projects/${projectId}/chat`, {
      method: "POST",
      body: JSON.stringify({
        content,
        file_ids: opts?.file_ids ?? null,
        thread_id: opts?.thread_id ?? null,
      }),
    }),

  streamChat: streamChat,

  listThreads: (projectId: number) =>
    request<ChatThread[]>(`/api/projects/${projectId}/threads`),
  createThread: (projectId: number, title?: string) =>
    request<ChatThread>(`/api/projects/${projectId}/threads`, {
      method: "POST",
      body: JSON.stringify({ title: title ?? null }),
    }),
  renameThread: (projectId: number, threadId: number, title: string) =>
    request<ChatThread>(`/api/projects/${projectId}/threads/${threadId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteThread: (projectId: number, threadId: number) =>
    request<void>(`/api/projects/${projectId}/threads/${threadId}`, {
      method: "DELETE",
    }),

  listFiles: (projectId: number) =>
    request<ProjectFile[]>(`/api/projects/${projectId}/files`),
  uploadFile: async (projectId: number, file: File) => {
    const fd = new FormData();
    fd.append("upload", file);
    const r = await fetch(`/api/projects/${projectId}/files`, {
      method: "POST",
      body: fd,
    });
    if (r.status === 401 && typeof window !== "undefined") {
      window.location.href = "/login";
      throw new ApiError(401, "Not authenticated");
    }
    if (!r.ok) {
      let message = `HTTP ${r.status}`;
      try {
        const body = (await r.json()) as { detail?: string };
        if (body.detail) message = body.detail;
      } catch {
        // ignore
      }
      throw new ApiError(r.status, message);
    }
    return (await r.json()) as ProjectFile;
  },
  deleteFile: (projectId: number, fileId: number) =>
    request<void>(`/api/projects/${projectId}/files/${fileId}`, {
      method: "DELETE",
    }),

  listDatasets: (projectId: number) =>
    request<DataQualityDataset[]>(`/api/projects/${projectId}/dq/datasets`),
  getDataset: (projectId: number, datasetId: number) =>
    request<DataQualityDataset>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}`,
    ),
  uploadDataset: async (projectId: number, file: File) => {
    const fd = new FormData();
    fd.append("upload", file);
    const r = await fetch(`/api/projects/${projectId}/dq/datasets`, {
      method: "POST",
      body: fd,
    });
    if (r.status === 401 && typeof window !== "undefined") {
      window.location.href = "/login";
      throw new ApiError(401, "Not authenticated");
    }
    if (!r.ok) {
      let message = `HTTP ${r.status}`;
      try {
        const body = (await r.json()) as { detail?: string };
        if (body.detail) message = body.detail;
      } catch {
        // ignore
      }
      throw new ApiError(r.status, message);
    }
    return (await r.json()) as DataQualityDataset;
  },
  deleteDataset: (projectId: number, datasetId: number) =>
    request<void>(`/api/projects/${projectId}/dq/datasets/${datasetId}`, {
      method: "DELETE",
    }),

  getLlmKeysStatus: () => request<LlmKeysStatus>("/api/auth/llm-keys"),
  setLlmKeys: (body: {
    provider: LlmProvider;
    llm_api_key: string;
    model?: string | null;
  }) =>
    request<LlmKeysStatus>("/api/auth/llm-keys", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  annotateDataset: (projectId: number, datasetId: number) =>
    request<DataQualityDataset>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/annotate`,
      { method: "POST" },
    ),
  getDatasetProfile: (projectId: number, datasetId: number) =>
    request<DqSheetProfile[]>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/profile`,
    ),
  listDatasetIssues: (
    projectId: number,
    datasetId: number,
    opts?: { sheet?: string; severity?: DqSeverity },
  ) => {
    const params = new URLSearchParams();
    if (opts?.sheet) params.set("sheet", opts.sheet);
    if (opts?.severity) params.set("severity", opts.severity);
    const qs = params.toString();
    return request<DqIssue[]>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/issues${qs ? `?${qs}` : ""}`,
    );
  },
  listFunctionalDependencies: (projectId: number, datasetId: number) =>
    request<DqFunctionalDependency[]>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/functional-dependencies`,
    ),
  listRelationships: (projectId: number, datasetId: number) =>
    request<DqRelationship[]>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/relationships`,
    ),
  updateRelationshipStatus: (
    projectId: number,
    datasetId: number,
    relationshipId: number,
    status: "confirmed" | "dismissed",
  ) =>
    request<DqRelationship>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/relationships/${relationshipId}`,
      { method: "PATCH", body: JSON.stringify({ status }) },
    ),
  setColumnBounds: (
    projectId: number,
    datasetId: number,
    sheet: string,
    column: string,
    body: { range_min: number | null; range_max: number | null },
  ) =>
    request<DqSheetProfile[]>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/sheets/${encodeURIComponent(sheet)}/columns/${encodeURIComponent(column)}/bounds`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),
  recomputeProfile: (projectId: number, datasetId: number) =>
    request<DqSheetProfile[]>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/profile`,
      { method: "POST" },
    ),
  listDqChat: (projectId: number, datasetId: number) =>
    request<ChatMessage[]>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/chat`,
    ),
  clearLlmKeys: () =>
    request<LlmKeysStatus>("/api/auth/llm-keys", { method: "DELETE" }),

  // --- Epic 3: similarity scoring ---

  getSimilarityConfig: (projectId: number, datasetId: number) =>
    request<DqConfigOrDraft>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/similarity/config`,
    ),
  saveSimilarityConfig: (
    projectId: number,
    datasetId: number,
    body: {
      sheet_a: string;
      sheet_b: string;
      normalization: Record<string, boolean>;
      threshold: number;
      mappings: DqColumnMapping[];
    },
  ) =>
    request<DqProfileConfig>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/similarity/config`,
      { method: "PUT", body: JSON.stringify(body) },
    ),
  recommendSimilarityConfig: (
    projectId: number,
    datasetId: number,
    body: { sheet_a: string; sheet_b: string },
  ) =>
    request<DqRecommendation>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/similarity/recommend`,
      {
        method: "POST",
        body: JSON.stringify({ ...body, existing_mappings: [] }),
      },
    ),
  recommendSimilarityConfigWithLlm: (
    projectId: number,
    datasetId: number,
    body: {
      sheet_a: string;
      sheet_b: string;
      existing_mappings: DqColumnMapping[];
    },
  ) =>
    request<DqRecommendation>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/similarity/recommend-llm`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  skipSimilarityConfig: (projectId: number, datasetId: number) =>
    request<{ config_completed_at: string }>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/similarity/skip`,
      { method: "POST" },
    ),
  runSimilarity: (projectId: number, datasetId: number) =>
    request<DqSimilarityRun>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/similarity/run`,
      { method: "POST" },
    ),
  listSimilarityRuns: (projectId: number, datasetId: number) =>
    request<DqSimilarityRun[]>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/similarity/runs`,
    ),
  listSimilarityClusters: (
    projectId: number,
    datasetId: number,
    runId: number,
  ) =>
    request<DqRecordCluster[]>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/similarity/runs/${runId}/clusters`,
    ),
  getSimilarityClusterDetail: (
    projectId: number,
    datasetId: number,
    runId: number,
    clusterId: number,
  ) =>
    request<DqClusterDetail>(
      `/api/projects/${projectId}/dq/datasets/${datasetId}/similarity/runs/${runId}/clusters/${clusterId}`,
    ),

  // --- IT Map Agent ---

  listItMapInventories: (projectId: number) =>
    request<ItMapInventory[]>(
      `/api/projects/${projectId}/it-map/inventories`,
    ),
  uploadItMapInventory: async (
    projectId: number,
    file: File,
  ): Promise<ItMapInventory> => {
    const fd = new FormData();
    fd.append("upload", file);
    const r = await fetch(`/api/projects/${projectId}/it-map/inventories`, {
      method: "POST",
      body: fd,
    });
    if (r.status === 401 && typeof window !== "undefined") {
      window.location.href = "/login";
      throw new ApiError(401, "Not authenticated");
    }
    if (!r.ok) {
      let message = `HTTP ${r.status}`;
      try {
        const body = (await r.json()) as { detail?: string };
        if (body.detail) message = body.detail;
      } catch {
        // ignore
      }
      throw new ApiError(r.status, message);
    }
    return (await r.json()) as ItMapInventory;
  },
  deleteItMapInventory: (projectId: number, inventoryId: number) =>
    request<void>(
      `/api/projects/${projectId}/it-map/inventories/${inventoryId}`,
      { method: "DELETE" },
    ),
  runItMapAgent: (projectId: number, inventoryId: number) =>
    request<ItMapAgentRun>(
      `/api/projects/${projectId}/it-map/inventories/${inventoryId}/run`,
      { method: "POST" },
    ),
  listItMapRuns: (projectId: number, inventoryId: number) =>
    request<ItMapAgentRun[]>(
      `/api/projects/${projectId}/it-map/inventories/${inventoryId}/runs`,
    ),
  listItMapApplications: (projectId: number, inventoryId: number) =>
    request<ItMapApplication[]>(
      `/api/projects/${projectId}/it-map/inventories/${inventoryId}/applications`,
    ),
  listProjectItMapApplications: (
    projectId: number,
    statusFilter?: ItMapMappingStatus,
  ) => {
    const qs = statusFilter ? `?status_filter=${statusFilter}` : "";
    return request<ItMapApplication[]>(
      `/api/projects/${projectId}/it-map/applications${qs}`,
    );
  },
  getItMapApplication: (projectId: number, applicationId: number) =>
    request<ItMapApplication>(
      `/api/projects/${projectId}/it-map/applications/${applicationId}`,
    ),
  updateItMapMappingStatus: (
    projectId: number,
    mappingId: number,
    status: "confirmed" | "dismissed",
  ) =>
    request<ItMapMapping>(
      `/api/projects/${projectId}/it-map/mappings/${mappingId}`,
      { method: "PATCH", body: JSON.stringify({ status }) },
    ),
  createItMapMapping: (
    projectId: number,
    body: { application_id: number; capability_id: number; rationale?: string },
  ) =>
    request<ItMapMapping>(`/api/projects/${projectId}/it-map/mappings`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
