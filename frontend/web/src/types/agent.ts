export type TestCaseItem = {
  id: string;
  category: string;
  topic: string;
  precondition: string;
  steps: string;
  expected: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
};

export type TestCaseModulePlan = {
  id: string;
  title: string;
  description: string;
  riskPoints: string[];
};

export type MindMapNodeData = {
  text: string;
  uid?: string;
  id?: string;
  tag?: string[];
  priority?: 'P0' | 'P1' | 'P2' | 'P3';
};

export type MindMapNode = {
  data: MindMapNodeData;
  children: MindMapNode[];
};

export type TestCaseAgentResult = {
  summary: string;
  cases: TestCaseItem[];
  mindMap: MindMapNode;
};

export type TestCasePlanResult = {
  summary: string;
  modules: TestCaseModulePlan[];
  mindMap: MindMapNode;
  /** /plan 在走通 MCP phase1 时返回，供 /module 复用以避免重复拉文档 */
  mcpDocumentBrief?: string | null;
};

export type ModuleTestCaseResult = {
  summary: string;
  module: TestCaseModulePlan;
  cases: TestCaseItem[];
  mindMap: MindMapNode;
};

export type ChatRole = 'user' | 'assistant';

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type MindMapChatResult = {
  assistantReply: string;
  mindMap: MindMapNode;
};
