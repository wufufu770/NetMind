export type Status='waiting'|'running'|'success'|'warning'|'failed'|'approval';
export interface IntentDSL{intent_id:string;business:string;description?:string;priority:string}
export interface AgentStep{agent:string;status:Status;duration_ms:number;tools:any[]}
export interface Execution{execution_id:string;status:Status;intent?:IntentDSL;steps:AgentStep[]}
