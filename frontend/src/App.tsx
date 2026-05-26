import {
  Bot,
  Brain,
  CalendarCheck,
  CarFront,
  ClipboardList,
  FileText,
  Gauge,
  GitBranch,
  GraduationCap,
  KeyRound,
  LogOut,
  NotebookTabs,
  Plus,
  ShieldCheck,
  Trash2,
  Upload,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

type User = {
  id: number;
  username: string;
  displayName: string;
  role: string;
  uploadQuotaMb?: number;
};

type NavKey =
  | "dashboard"
  | "pptReader"
  | "pptManagement"
  | "reminders"
  | "apiSettings"
  | "study"
  | "cards"
  | "quiz"
  | "reviews"
  | "parking"
  | "mainline"
  | "mistakes"
  | "admin";

type ApiProvider = {
  providerKey: string;
  name: string;
  providerType: string;
  baseUrl?: string;
  model?: string;
  authType?: string;
  enabled: boolean;
  sortOrder: number;
  balanceQueryEnabled?: boolean;
};

type StudySession = {
  id: number;
  date: string;
  subject: string;
  chapter?: string;
  title: string;
  mainQuestion: string;
  masteredContent?: string;
  blockers?: string;
  wrongQuestions?: string;
  summary?: string;
  mastery: number;
  needReview: boolean;
  key: boolean;
};

type KnowledgeCard = {
  id: number;
  subject: string;
  topic: string;
  coreQuestion?: string;
  oneSentence: string;
  logicOrFormula?: string;
  application?: string;
  mastery: number;
  needReview: boolean;
};

type ParkingItem = {
  id: number;
  subject?: string;
  question: string;
  source?: string;
  status?: string;
};

type Mistake = {
  id: number;
  subject?: string;
  topic?: string;
  originalQuestion: string;
  correctIdea: string;
  causeCategory: string;
  summary?: string;
};

type ReviewTask = {
  id: number;
  taskType?: string;
  subject?: string;
  title?: string;
  prompt?: string;
  dueDate?: string;
  status?: string;
};

type Deck = {
  id: number;
  filename?: string;
  title: string;
  subject?: string;
  category?: string;
  status?: string;
  slideCount?: number;
};

type ReaderSlide = {
  slide: {
    id: number;
    slideNumber: number;
    title?: string;
    slideText?: string;
    notes?: string;
  };
  latestExplanation?: {
    id: number;
    explanation: string;
  } | null;
  imageUrl?: string;
  slideNumber: number;
  title?: string;
  markdown?: string;
  rawText?: string;
  explanation?: string;
};

type ReaderPayload = {
  deck: Deck;
  slides: ReaderSlide[];
  sections?: { id: number; title: string; startSlideNumber: number; endSlideNumber?: number }[];
};

type AdminUser = {
  id: number;
  username: string;
  displayName: string;
  role: string;
  active: boolean;
  uploadQuotaMb: number;
};

type Invite = {
  code: string;
  role?: string;
  active: boolean;
  maxUses?: number;
  usedCount?: number;
};

const api = {
  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers);
    if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, { ...options, headers, credentials: "include" });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `${response.status} ${response.statusText}`);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  },
  get<T>(path: string) {
    return api.request<T>(path);
  },
  post<T>(path: string, body?: unknown) {
    return api.request<T>(path, {
      method: "POST",
      body: body instanceof FormData ? body : JSON.stringify(body ?? {}),
    });
  },
  put<T>(path: string, body: unknown) {
    return api.request<T>(path, { method: "PUT", body: JSON.stringify(body) });
  },
  patch<T>(path: string, body: unknown) {
    return api.request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
  },
  delete(path: string) {
    return api.request<void>(path, { method: "DELETE" });
  },
};

const navItems: { key: NavKey; label: string; icon: typeof Gauge; adminOnly?: boolean }[] = [
  { key: "dashboard", label: "首页 Dashboard", icon: Gauge },
  { key: "pptReader", label: "PPT 逐页讲解", icon: FileText },
  { key: "pptManagement", label: "PPT 与插问管理", icon: NotebookTabs },
  { key: "reminders", label: "每日复盘提醒", icon: CalendarCheck },
  { key: "apiSettings", label: "API 接入设置", icon: KeyRound },
  { key: "study", label: "学习登记", icon: GraduationCap },
  { key: "cards", label: "知识点卡片", icon: Brain },
  { key: "quiz", label: "闭卷测试 Prompt", icon: ClipboardList },
  { key: "reviews", label: "复习计划", icon: CalendarCheck },
  { key: "parking", label: "探索停车场", icon: CarFront },
  { key: "mainline", label: "主线与插问", icon: GitBranch },
  { key: "mistakes", label: "错因本", icon: ClipboardList },
  { key: "admin", label: "管理员后台", icon: ShieldCheck, adminOnly: true },
];

const emptyStudy: Omit<StudySession, "id"> & { createKnowledgeCard: boolean } = {
  date: new Date().toISOString().slice(0, 10),
  subject: "",
  chapter: "",
  title: "",
  mainQuestion: "",
  masteredContent: "",
  blockers: "",
  wrongQuestions: "",
  summary: "",
  mastery: 70,
  needReview: true,
  key: false,
  createKnowledgeCard: false,
};

const emptyCard = {
  subject: "",
  topic: "",
  coreQuestion: "",
  oneSentence: "",
  logicOrFormula: "",
  application: "",
  mastery: 70,
  needReview: true,
  sourceSessionId: undefined as number | undefined,
};

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [initialized, setInitialized] = useState<boolean | null>(null);
  const [active, setActive] = useState<NavKey>("dashboard");
  const [error, setError] = useState("");

  function loadBootstrap() {
    setError("");
    setInitialized(null);
    Promise.allSettled([api.get<{ adminInitialized?: boolean; initialized?: boolean }>("/api/auth/status"), api.get<User>("/api/auth/me")]).then(
      ([status, me]) => {
        if (status.status === "fulfilled") {
          setInitialized(Boolean(status.value.adminInitialized ?? status.value.initialized));
        } else {
          setInitialized(true);
          setError("无法连接后端服务，请先启动 Spring Boot：cd backend && mvn spring-boot:run");
        }
        if (me.status === "fulfilled") setUser(me.value);
      },
    );
  }

  useEffect(() => {
    loadBootstrap();
  }, []);

  if (initialized === null) return <div className="boot">正在连接本地学习服务...</div>;
  if (!user) return <AuthGate initialized={initialized} bootstrapError={error} onRetry={loadBootstrap} onUser={setUser} />;

  const availableNav = navItems.filter((item) => !item.adminOnly || user.role === "admin");
  const ActiveIcon = availableNav.find((item) => item.key === active)?.icon ?? Gauge;

  async function logout() {
    await api.post("/api/auth/logout");
    setUser(null);
    setActive("dashboard");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">INTP</div>
          <div>
            <h1>INTP Study Manager</h1>
            <p>问题驱动 · 闭卷回忆 · 错因分析 · 间隔复习</p>
          </div>
        </div>
        <div className="user-card">
          <strong>{user.displayName || user.username}</strong>
          <span>@{user.username}</span>
          <span>角色：{user.role}</span>
          <span>上传容量：{user.uploadQuotaMb ?? "-"} MB</span>
          <button className="ghost danger" onClick={logout}>
            <LogOut size={16} /> 退出登录
          </button>
        </div>
        <nav className="nav-list">
          {availableNav.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.key} className={active === item.key ? "active" : ""} onClick={() => setActive(item.key)}>
                <Icon size={17} />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className="principle">
          <strong>70% 原则</strong>
          <span>低于 70% 的知识点优先进入复习、错因和追问闭环。</span>
        </div>
      </aside>
      <main className="content">
        <header className="page-header">
          <div>
            <span className="eyebrow">Spring Boot · React · Tauri</span>
            <h2>
              <ActiveIcon size={24} />
              {availableNav.find((item) => item.key === active)?.label}
            </h2>
          </div>
          {error && <button className="error-pill" onClick={() => setError("")}>{error}</button>}
        </header>
        <PageRouter active={active} setError={setError} user={user} />
      </main>
    </div>
  );
}

function AuthGate({
  initialized,
  bootstrapError,
  onRetry,
  onUser,
}: {
  initialized: boolean;
  bootstrapError?: string;
  onRetry: () => void;
  onUser: (user: User) => void;
}) {
  const [mode, setMode] = useState(initialized ? "login" : "setup");
  const [form, setForm] = useState({ username: "", displayName: "", password: "", confirmPassword: "", inviteCode: "" });
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      if (mode === "setup") {
        if (form.password !== form.confirmPassword) throw new Error("两次密码不一致");
        onUser(await api.post<User>("/api/auth/setup-admin", form));
      } else if (mode === "login") {
        onUser(await api.post<User>("/api/auth/login", { username: form.username, password: form.password }));
      } else {
        onUser(await api.post<User>("/api/auth/register-by-invite", form));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "认证失败");
    }
  }

  return (
    <div className="auth-page">
      <section className="auth-panel">
        <div className="brand auth-brand">
          <div className="brand-mark">INTP</div>
          <div>
            <h1>INTP Study Manager</h1>
            <p>问题驱动 · 闭卷回忆 · 错因分析 · 间隔复习</p>
          </div>
        </div>
        <div className="tabs">
          {!initialized && <button className={mode === "setup" ? "selected" : ""} onClick={() => setMode("setup")}>首次管理员创建</button>}
          <button className={mode === "login" ? "selected" : ""} onClick={() => setMode("login")}>登录</button>
          <button className={mode === "invite" ? "selected" : ""} onClick={() => setMode("invite")}>邀请码加入</button>
        </div>
        {bootstrapError && (
          <div className="connection-warning">
            <span>{bootstrapError}</span>
            <button type="button" onClick={onRetry}>重新连接</button>
          </div>
        )}
        <form className="form-grid" onSubmit={submit}>
          <label>用户名<input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
          {(mode === "setup" || mode === "invite") && (
            <label>显示名称<input value={form.displayName} onChange={(e) => setForm({ ...form, displayName: e.target.value })} /></label>
          )}
          <label>密码<input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
          {mode === "setup" && (
            <label>确认密码<input type="password" value={form.confirmPassword} onChange={(e) => setForm({ ...form, confirmPassword: e.target.value })} /></label>
          )}
          {mode === "invite" && <label>邀请码<input value={form.inviteCode} onChange={(e) => setForm({ ...form, inviteCode: e.target.value })} /></label>}
          {error && <div className="form-error">{error}</div>}
          <button className="primary">{mode === "setup" ? "创建管理员" : mode === "login" ? "登录" : "加入"}</button>
        </form>
      </section>
    </div>
  );
}

function PageRouter({ active, setError, user }: { active: NavKey; setError: (error: string) => void; user: User }) {
  const props = { setError };
  switch (active) {
    case "dashboard":
      return <DashboardPage {...props} />;
    case "study":
      return <StudyPage {...props} />;
    case "cards":
      return <KnowledgeCardsPage {...props} />;
    case "reviews":
      return <ReviewsPage {...props} />;
    case "parking":
      return <ParkingPage {...props} />;
    case "mistakes":
      return <MistakesPage {...props} />;
    case "apiSettings":
      return <ApiSettingsPage {...props} />;
    case "pptReader":
      return <PptReaderPage {...props} />;
    case "pptManagement":
      return <PptManagementPage {...props} />;
    case "reminders":
      return <ReminderPage {...props} />;
    case "admin":
      return user.role === "admin" ? <AdminPage {...props} /> : <EmptyState title="仅管理员可访问" />;
    case "mainline":
      return <MainlinePage />;
    case "quiz":
      return <QuizPromptPage />;
  }
}

function DashboardPage({ setError }: { setError: (error: string) => void }) {
  const [summary, setSummary] = useState<any>(null);
  useEffect(() => {
    api.get("/api/dashboard/summary").then(setSummary).catch((err) => setError(err.message));
  }, [setError]);
  const counts = summary?.counts ?? {};
  return (
    <section className="stack">
      <div className="metric-grid">
        <Metric label="今日待复习" value={counts.dueReviewTasks ?? summary?.dueReviewTasks?.length ?? 0} />
        <Metric label="低于 70% 知识点" value={counts.lowMasteryCards ?? summary?.lowMasteryCards?.length ?? 0} />
        <Metric label="最近卡点" value={summary?.recentBlockers?.length ?? 0} />
        <Metric label="停车场未解决" value={summary?.openParkingQuestions?.length ?? 0} />
      </div>
      <div className="two-col">
        <Panel title="每日复盘提醒">
          <p className="muted">日期：{summary?.today ?? new Date().toISOString().slice(0, 10)}</p>
          <p>状态：{summary?.reminder?.doneToday ? "今日已完成" : "等待复盘"}</p>
        </Panel>
        <Panel title="每日 AI 轻量复习">
          <DailyAiReviewMini setError={setError} />
        </Panel>
      </div>
      <DataList title="今日复习列表" rows={summary?.dueReviewTasks ?? []} pick={(item: any) => item.title || item.prompt || item.subject} />
      <DataList title="低掌握度知识点" rows={summary?.lowMasteryCards ?? []} pick={(item: any) => `${item.topic ?? ""} ${item.mastery ?? ""}%`} />
      <DataList title="最近知识双链 / 停车场问题" rows={[...(summary?.recentKnowledgeLinks ?? []), ...(summary?.openParkingQuestions ?? [])]} pick={(item: any) => item.question || item.reason || item.topic || item.title} />
    </section>
  );
}

function DailyAiReviewMini({ setError }: { setError: (error: string) => void }) {
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState("");
  async function generate() {
    try {
      const plan = await api.post<any>("/api/reviews/ai-plan", { providerKey: null, maxTokens: 1200 });
      setResult(plan.content || plan.planJson || JSON.stringify(plan, null, 2));
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    }
  }
  async function evaluate() {
    try {
      const review = await api.post<any>("/api/reviews/ai-plan/evaluate", { answer });
      setResult(JSON.stringify(review, null, 2));
    } catch (err) {
      setError(err instanceof Error ? err.message : "批改失败");
    }
  }
  return (
    <div className="stack compact">
      <div className="inline-actions">
        <button className="primary" onClick={generate}>生成 / 重新生成</button>
        <button onClick={evaluate}>AI 批改结果</button>
      </div>
      <textarea placeholder="自测答题" value={answer} onChange={(e) => setAnswer(e.target.value)} />
      {result && <pre className="output">{result}</pre>}
    </div>
  );
}

function StudyPage({ setError }: { setError: (error: string) => void }) {
  const [items, setItems] = useState<StudySession[]>([]);
  const [form, setForm] = useState(emptyStudy);
  const [filter, setFilter] = useState("");
  const refresh = () => api.get<StudySession[]>("/api/study-sessions").then(setItems).catch((err) => setError(err.message));
  useEffect(() => {
    refresh();
  }, []);
  const shown = filter ? items.filter((item) => item.subject?.includes(filter)) : items;
  async function submit(event: FormEvent) {
    event.preventDefault();
    await api.post("/api/study-sessions", form).catch((err) => setError(err.message));
    setForm(emptyStudy);
    refresh();
  }
  return (
    <CrudLayout title="新建学习登记" form={
      <form className="form-grid" onSubmit={submit}>
        <Field label="日期"><input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></Field>
        <Field label="科目"><input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} /></Field>
        <Field label="章节 / PPT / 课程名称"><input value={form.chapter} onChange={(e) => setForm({ ...form, chapter: e.target.value })} /></Field>
        <Field label="今日学习主题"><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
        <Field label="核心问题"><textarea value={form.mainQuestion} onChange={(e) => setForm({ ...form, mainQuestion: e.target.value })} /></Field>
        <Field label="已掌握内容"><textarea value={form.masteredContent} onChange={(e) => setForm({ ...form, masteredContent: e.target.value })} /></Field>
        <Field label="卡点"><textarea value={form.blockers} onChange={(e) => setForm({ ...form, blockers: e.target.value })} /></Field>
        <Field label="错题或不会的问题"><textarea value={form.wrongQuestions} onChange={(e) => setForm({ ...form, wrongQuestions: e.target.value })} /></Field>
        <Field label="主线讲解整理 / 总结"><textarea value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} /></Field>
        <Field label="掌握度"><input type="range" min="0" max="100" value={form.mastery} onChange={(e) => setForm({ ...form, mastery: Number(e.target.value) })} /><span>{form.mastery}%</span></Field>
        <Check label="需要复习" checked={form.needReview} onChange={(needReview) => setForm({ ...form, needReview })} />
        <Check label="加入重点知识点" checked={form.key} onChange={(key) => setForm({ ...form, key })} />
        <Check label="同时创建知识点卡片" checked={form.createKnowledgeCard} onChange={(createKnowledgeCard) => setForm({ ...form, createKnowledgeCard })} />
        <button className="primary"><Plus size={16} /> 保存学习登记</button>
      </form>
    }>
      <Toolbar><input placeholder="按科目筛选" value={filter} onChange={(e) => setFilter(e.target.value)} /></Toolbar>
      <Table rows={shown} columns={["date", "subject", "title", "mainQuestion", "mastery"]} onDelete={(id) => api.delete(`/api/study-sessions/${id}`).then(refresh)} />
    </CrudLayout>
  );
}

function KnowledgeCardsPage({ setError }: { setError: (error: string) => void }) {
  const [items, setItems] = useState<KnowledgeCard[]>([]);
  const [form, setForm] = useState(emptyCard);
  const refresh = () => api.get<KnowledgeCard[]>("/api/knowledge-cards").then(setItems).catch((err) => setError(err.message));
  useEffect(() => {
    refresh();
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await api.post("/api/knowledge-cards", form).catch((err) => setError(err.message));
    setForm(emptyCard);
    refresh();
  }
  return (
    <CrudLayout title="新建知识点卡片" form={
      <form className="form-grid" onSubmit={submit}>
        <Field label="科目"><input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} /></Field>
        <Field label="知识点"><input value={form.topic} onChange={(e) => setForm({ ...form, topic: e.target.value })} /></Field>
        <Field label="核心问题"><textarea value={form.coreQuestion} onChange={(e) => setForm({ ...form, coreQuestion: e.target.value })} /></Field>
        <Field label="一句话解释"><textarea value={form.oneSentence} onChange={(e) => setForm({ ...form, oneSentence: e.target.value })} /></Field>
        <Field label="公式 / 逻辑推导"><textarea value={form.logicOrFormula} onChange={(e) => setForm({ ...form, logicOrFormula: e.target.value })} /></Field>
        <Field label="典型题 / 应用场景"><textarea value={form.application} onChange={(e) => setForm({ ...form, application: e.target.value })} /></Field>
        <Field label="掌握度"><input type="range" min="0" max="100" value={form.mastery} onChange={(e) => setForm({ ...form, mastery: Number(e.target.value) })} /><span>{form.mastery}%</span></Field>
        <Check label="创建 1-3-7-14 复习任务" checked={form.needReview} onChange={(needReview) => setForm({ ...form, needReview })} />
        <button className="primary"><Plus size={16} /> 保存知识点</button>
      </form>
    }>
      <Table rows={items} columns={["subject", "topic", "oneSentence", "mastery", "needReview"]} onDelete={(id) => api.delete(`/api/knowledge-cards/${id}`).then(refresh)} />
      <Panel title="知识双链">
        <p className="muted">出链 / 入链、关系类型、连接理由、联系/对比要点已在后端保留接口，下一轮可接入可视化编辑。</p>
      </Panel>
    </CrudLayout>
  );
}

function ReviewsPage({ setError }: { setError: (error: string) => void }) {
  const [due, setDue] = useState<ReviewTask[]>([]);
  const [all, setAll] = useState<ReviewTask[]>([]);
  const refresh = () => {
    api.get<ReviewTask[]>("/api/reviews/due").then(setDue).catch((err) => setError(err.message));
    api.get<ReviewTask[]>("/api/reviews/tasks").then(setAll).catch((err) => setError(err.message));
  };
  useEffect(() => {
    refresh();
  }, []);
  async function mark(id: number, result: string) {
    await api.post(`/api/reviews/tasks/${id}/result`, { result }).catch((err) => setError(err.message));
    refresh();
  }
  return (
    <section className="stack">
      <Panel title="今日复习表">
        <Table rows={due} columns={["dueDate", "subject", "title", "status"]} />
        <div className="inline-actions">
          {due[0] && ["完全掌握", "基本掌握", "仍然模糊", "完全不会"].map((label) => <button key={label} onClick={() => mark(due[0].id, label)}>{label}</button>)}
        </div>
      </Panel>
      <Panel title="全部待复习表">
      <Table rows={all} columns={["reviewDate", "subject", "topic", "reviewStage", "status"]} />
      </Panel>
    </section>
  );
}

function ParkingPage({ setError }: { setError: (error: string) => void }) {
  const [items, setItems] = useState<ParkingItem[]>([]);
  const [form, setForm] = useState({ subject: "", source: "", question: "", status: "open" });
  const refresh = () => api.get<ParkingItem[]>("/api/parking-lot").then(setItems).catch((err) => setError(err.message));
  useEffect(() => {
    refresh();
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await api.post("/api/parking-lot", form).catch((err) => setError(err.message));
    setForm({ subject: "", source: "", question: "", status: "open" });
    refresh();
  }
  return (
    <CrudLayout title="添加探索停车场问题" form={
      <form className="form-grid" onSubmit={submit}>
        <Field label="科目"><input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} /></Field>
        <Field label="来源"><input value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} /></Field>
        <Field label="问题"><textarea value={form.question} onChange={(e) => setForm({ ...form, question: e.target.value })} /></Field>
        <button className="primary">保存问题</button>
      </form>
    }>
      <Table rows={items} columns={["subject", "question", "source", "status"]} onDelete={(id) => api.delete(`/api/parking-lot/${id}`).then(refresh)} extra={(row) => <button onClick={() => api.post(`/api/parking-lot/${row.id}/resolve`).then(refresh)}>标记已解决</button>} />
    </CrudLayout>
  );
}

function MistakesPage({ setError }: { setError: (error: string) => void }) {
  const [items, setItems] = useState<Mistake[]>([]);
  const [form, setForm] = useState({ subject: "", topic: "", knowledgeId: undefined, originalQuestion: "", myWrongAnswer: "", correctIdea: "", causeCategory: "", warningSignal: "", summary: "", addToReview: true });
  const refresh = () => api.get<Mistake[]>("/api/mistakes").then(setItems).catch((err) => setError(err.message));
  useEffect(() => {
    refresh();
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await api.post("/api/mistakes", form).catch((err) => setError(err.message));
    refresh();
  }
  const stats = useMemo(() => {
    const map = new Map<string, number>();
    items.forEach((item) => map.set(item.causeCategory, (map.get(item.causeCategory) ?? 0) + 1));
    return Array.from(map.entries());
  }, [items]);
  return (
    <CrudLayout title="记录错因" form={
      <form className="form-grid" onSubmit={submit}>
        {["subject:科目", "topic:知识点", "originalQuestion:原题 / 原问题", "myWrongAnswer:我的错误回答", "correctIdea:正确思路", "causeCategory:错因分类", "warningSignal:下次看到什么信号要警惕", "summary:一句话总结"].map((item) => {
          const [key, label] = item.split(":") as [keyof typeof form, string];
          return <Field key={key} label={label}><textarea value={String(form[key] ?? "")} onChange={(e) => setForm({ ...form, [key]: e.target.value })} /></Field>;
        })}
        <Check label="加入复习队列" checked={form.addToReview} onChange={(addToReview) => setForm({ ...form, addToReview })} />
        <button className="primary">保存错因</button>
      </form>
    }>
      <Panel title="高频错因统计">{stats.map(([name, count]) => <span className="tag" key={name}>{name}: {count}</span>)}</Panel>
      <Table rows={items} columns={["subject", "topic", "originalQuestion", "causeCategory", "summary"]} onDelete={(id) => api.delete(`/api/mistakes/${id}`).then(refresh)} />
    </CrudLayout>
  );
}

function ApiSettingsPage({ setError }: { setError: (error: string) => void }) {
  const [providers, setProviders] = useState<ApiProvider[]>([]);
  const [form, setForm] = useState({ name: "", providerType: "openai-compatible", baseUrl: "", model: "", apiKeyEnv: "", authType: "bearer", extraHeadersJson: "", requestTemplateJson: "", responsePath: "", balanceQueryEnabled: false, balanceQueryType: "", balanceQueryConfigJson: "", enabled: true, sortOrder: 100 });
  const [testResult, setTestResult] = useState("");
  const refresh = () => api.get<ApiProvider[]>("/api/ai/providers").then(setProviders).catch((err) => setError(err.message));
  useEffect(() => {
    refresh();
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await api.post("/api/ai/providers", form).catch((err) => setError(err.message));
    refresh();
  }
  async function test(providerKey: string) {
    const result = await api.post<any>(`/api/ai/providers/${providerKey}/test`, { prompt: "请用一句话回答：连接正常。" }).catch((err) => setError(err.message));
    if (result) setTestResult(result.text || JSON.stringify(result, null, 2));
  }
  return (
    <section className="stack">
      <div className="tabs wrap">
        {["编号 / 删除", "余额查询", "编辑 Provider", "新增自定义 API", "加密 API Key", "测试调用", "填写参考"].map((tab) => <button className="selected" key={tab}>{tab}</button>)}
      </div>
      <CrudLayout title="新增自定义 API" form={
        <form className="form-grid" onSubmit={submit}>
          <Field label="Provider 名称"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Provider 类型"><input value={form.providerType} onChange={(e) => setForm({ ...form, providerType: e.target.value })} /></Field>
          <Field label="Base URL"><input value={form.baseUrl} onChange={(e) => setForm({ ...form, baseUrl: e.target.value })} /></Field>
          <Field label="默认模型"><input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></Field>
          <Field label="API Key 环境变量 / 密钥名"><input value={form.apiKeyEnv} onChange={(e) => setForm({ ...form, apiKeyEnv: e.target.value })} /></Field>
          <Check label="启用" checked={form.enabled} onChange={(enabled) => setForm({ ...form, enabled })} />
          <Check label="启用余额查询" checked={form.balanceQueryEnabled} onChange={(balanceQueryEnabled) => setForm({ ...form, balanceQueryEnabled })} />
          <button className="primary">保存 Provider</button>
        </form>
      }>
        <Table rows={providers} columns={["sortOrder", "name", "providerType", "model", "enabled"]} onDelete={(id) => api.delete(`/api/ai/providers/${id}`).then(refresh)} idKey="providerKey" extra={(row) => <button onClick={() => test(row.providerKey)}>测试调用</button>} />
        {testResult && <pre className="output">{testResult}</pre>}
        <Panel title="加密 API Key">
          <p className="muted">密钥库状态与写入接口已由后端提供，首版前端保留入口；业务调用仍统一经后端 Provider。</p>
        </Panel>
      </CrudLayout>
    </section>
  );
}

function PptReaderPage({ setError }: { setError: (error: string) => void }) {
  const [decks, setDecks] = useState<Deck[]>([]);
  const [deckId, setDeckId] = useState<number | "">("");
  const [payload, setPayload] = useState<ReaderPayload | null>(null);
  const [index, setIndex] = useState(0);
  const [question, setQuestion] = useState("");
  const [rightOpen, setRightOpen] = useState(true);
  const slide = payload?.slides[index];
  const refreshDecks = () => api.get<Deck[]>("/api/ppt/decks").then(setDecks).catch((err) => setError(err.message));
  useEffect(() => {
    refreshDecks();
  }, []);
  useEffect(() => {
    if (!deckId) return;
    api.get<ReaderPayload>(`/api/ppt/decks/${deckId}/reader-window`).then((data) => {
      setPayload(data);
      setIndex(0);
    }).catch((err) => setError(err.message));
  }, [deckId, setError]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "PageDown" || event.key === "ArrowDown") setIndex((value) => Math.min(value + 1, (payload?.slides.length ?? 1) - 1));
      if (event.key === "PageUp" || event.key === "ArrowUp") setIndex((value) => Math.max(value - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [payload]);
  async function upload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const data = new FormData();
    data.set("file", file);
    data.set("title", file.name);
    const imported = await api.post<any>("/api/ppt/decks", data).catch((err) => setError(err.message));
    refreshDecks();
    if (imported?.deckId) setDeckId(imported.deckId);
  }
  async function saveQuestion() {
    if (!deckId || !slide) return;
    await api.post(`/api/ppt/decks/${deckId}/slides/${slide.slide.id}/questions`, { question, answer: "待回答", status: "open" }).catch((err) => setError(err.message));
    setQuestion("");
  }
  async function savePosition() {
    if (!deckId || !slide) return;
    await api.put(`/api/ppt/decks/${deckId}/reader-position`, { deckId, slideId: slide.slide.id, slideNumber: slide.slide.slideNumber }).catch((err) => setError(err.message));
  }
  return (
    <section className="stack reader-page">
      <Panel title="资料与 AI 设置">
        <div className="reader-toolbar">
          <select value={deckId} onChange={(e) => setDeckId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">选择资料</option>
            {decks.map((deck) => <option key={deck.id} value={deck.id}>{deck.title || deck.filename}</option>)}
          </select>
          <label className="file-button"><Upload size={16} /> 上传 PPT/PDF<input type="file" accept=".pdf,.ppt,.pptx" onChange={upload} /></label>
          <button>整份资料逐页分析</button>
          <button>目录分块</button>
          <input className="short" placeholder="生成范围" />
          <button onClick={savePosition}>保存阅读位置</button>
          <button onClick={() => document.documentElement.requestFullscreen?.()}>全屏</button>
        </div>
      </Panel>
      {payload ? (
        <div className={`reader-grid ${rightOpen ? "" : "right-closed"}`} onWheel={(e) => {
          if (Math.abs(e.deltaY) > 20) setIndex((value) => Math.max(0, Math.min(value + (e.deltaY > 0 ? 1 : -1), payload.slides.length - 1)));
        }}>
          <aside className="reader-index">
            <select value={index} onChange={(e) => setIndex(Number(e.target.value))}>
              {payload.slides.map((item, i) => <option key={item.slide.id} value={i}>第 {item.slide.slideNumber} 页 {item.slide.title}</option>)}
            </select>
            {payload.sections?.map((section) => (
              <button key={section.id} onClick={() => setIndex(Math.max(0, payload.slides.findIndex((s) => s.slide.slideNumber === section.startSlideNumber)))}>
                {section.title}
              </button>
            ))}
            <div className="inline-actions"><button>逐页</button><button>连续</button></div>
          </aside>
          <div className="slide-pane">
            {slide && <img src={slide.imageUrl || `/api/ppt/decks/${deckId}/slides/${slide.slide.id}/image`} alt={`第 ${slide.slide.slideNumber} 页`} />}
          </div>
          <article className="explain-pane">
            <h3>第 {slide?.slide.slideNumber} 页逐页讲解</h3>
            <textarea value={slide?.latestExplanation?.explanation || slide?.slide.slideText || slide?.slide.notes || ""} readOnly />
            <button>编辑讲解并保存</button>
          </article>
          {rightOpen && (
            <aside className="question-pane">
              <button className="ghost" onClick={() => setRightOpen(false)}>收起插问栏</button>
              <textarea placeholder="侧边插问，不覆盖主线讲解" value={question} onChange={(e) => setQuestion(e.target.value)} />
              <button className="primary" onClick={saveQuestion}>发送并保存到当前页</button>
              <div className="inline-actions"><button>引用到插问</button><button>高亮 / 取消高亮</button><button>复制引用</button></div>
            </aside>
          )}
          {!rightOpen && <button className="restore-side" onClick={() => setRightOpen(true)}>展开插问栏</button>}
        </div>
      ) : <EmptyState title="请选择或上传 PPT/PDF 资料" />}
    </section>
  );
}

function PptManagementPage({ setError }: { setError: (error: string) => void }) {
  const [decks, setDecks] = useState<Deck[]>([]);
  useEffect(() => {
    api.get<Deck[]>("/api/ppt/decks").then(setDecks).catch((err) => setError(err.message));
  }, [setError]);
  return (
    <section className="stack">
      <div className="tabs"><button className="selected">PPT / PDF 资料</button><button>插问记录</button></div>
      <Toolbar><input placeholder="状态 / 分类 / 关键词筛选" /></Toolbar>
      <Table rows={decks} columns={["title", "subject", "filename", "slideCount", "status"]} />
      <Panel title="插问记录">
        <p className="muted">页码、状态、分类、关键词筛选入口已保留；插问记录依赖后端聚合接口后补齐。</p>
      </Panel>
    </section>
  );
}

function ReminderPage({ setError }: { setError: (error: string) => void }) {
  const [status, setStatus] = useState<any>(null);
  useEffect(() => {
    api.get("/api/reminders/daily-review").then(setStatus).catch((err) => setError(err.message));
  }, [setError]);
  return (
    <Panel title="每日复盘提醒">
      <p>今日状态：{status?.doneToday ? "已完成" : "未完成"}</p>
      <button className="primary" onClick={() => api.post("/api/reminders/daily-review/done", { notes: "React 前端标记完成" }).then(() => api.get("/api/reminders/daily-review").then(setStatus))}>标记今日完成</button>
    </Panel>
  );
}

function AdminPage({ setError }: { setError: (error: string) => void }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [quota, setQuota] = useState(1024);
  const refresh = () => {
    api.get<AdminUser[]>("/api/admin/users").then(setUsers).catch((err) => setError(err.message));
    api.get<Invite[]>("/api/admin/invites").then(setInvites).catch((err) => setError(err.message));
  };
  useEffect(refresh, []);
  return (
    <section className="stack">
      <div className="tabs"><button className="selected">创建邀请码</button><button>邀请码管理</button><button>用户管理</button></div>
      <Panel title="创建邀请码">
        <div className="inline-actions">
          <input type="number" value={quota} onChange={(e) => setQuota(Number(e.target.value))} />
          <button className="primary" onClick={() => api.post("/api/admin/invites", { role: "user", maxUses: 1, uploadQuotaMb: quota }).then(refresh)}>创建邀请码</button>
        </div>
      </Panel>
      <Table rows={invites} columns={["code", "role", "active", "maxUses", "usedCount"]} idKey="code" />
      <Table rows={users} columns={["username", "displayName", "role", "active", "uploadQuotaMb"]} extra={(row) => <button onClick={() => api.patch(`/api/admin/users/${row.id}/active`, { active: !row.active }).then(refresh)}>{row.active ? "禁用" : "启用"}</button>} />
    </section>
  );
}

function MainlinePage() {
  return <section className="stack"><div className="tabs"><button className="selected">主线锚点</button><button>插问分支</button><button>完整脉络</button></div><EmptyState title="主线锚点 / 插问分支接口已完成，下一轮接入可编辑表单" /></section>;
}

function QuizPromptPage() {
  return <Panel title="闭卷测试 Prompt"><textarea readOnly value={"请围绕今天的核心问题生成闭卷回忆测试，并要求我先回答再评分。"} /></Panel>;
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="panel"><h3>{title}</h3>{children}</section>;
}

function CrudLayout({ title, form, children }: { title: string; form: React.ReactNode; children: React.ReactNode }) {
  return <section className="crud-grid"><Panel title={title}>{form}</Panel><div className="stack">{children}</div></section>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label>{label}{children}</label>;
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="check"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />{label}</label>;
}

function Toolbar({ children }: { children: React.ReactNode }) {
  return <div className="toolbar">{children}</div>;
}

function Table<T extends Record<string, any>>({ rows, columns, onDelete, extra, idKey = "id" }: { rows: T[]; columns: string[]; onDelete?: (id: any) => void; extra?: (row: T) => React.ReactNode; idKey?: string }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((col) => <th key={col}>{col}</th>)}{(onDelete || extra) && <th>操作</th>}</tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row[idKey])}>
              {columns.map((col) => <td key={col}>{String(row[col] ?? "")}</td>)}
              {(onDelete || extra) && <td className="actions">{extra?.(row)}{onDelete && <button className="icon danger" onClick={() => onDelete(row[idKey])}><Trash2 size={15} /></button>}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <div className="empty-row">暂无数据</div>}
    </div>
  );
}

function DataList({ title, rows, pick }: { title: string; rows: any[]; pick: (row: any) => string }) {
  return <Panel title={title}>{rows.length ? rows.map((row, index) => <div className="list-row" key={row.id ?? index}>{pick(row)}</div>) : <p className="muted">暂无数据</p>}</Panel>;
}

function EmptyState({ title }: { title: string }) {
  return <div className="empty-state">{title}</div>;
}
