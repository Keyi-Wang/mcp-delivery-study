/* Compile unchanged pinned TS function declarations; control only external
 * collaborators. No network, full SDK deployment, or inference is claimed. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const crypto = require('crypto');
const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'artifacts/mcp-acceptance-study');
const ts = require(process.env.MCP_TYPESCRIPT_PATH || path.join(ROOT, '.mcp-ts-runtime/node_modules/typescript'));
const sha = text => crypto.createHash('sha256').update(text).digest('hex');
const clone = value => JSON.parse(JSON.stringify(value));
const selections = [];
function declarations(version, file, names) {
  const filename = path.join(OUT, 'sources/adcp-' + version, file);
  const source = fs.readFileSync(filename, 'utf8');
  const parsed = ts.createSourceFile(filename, source, ts.ScriptTarget.ES2022, true);
  const nodes = parsed.statements.filter(n => ts.isFunctionDeclaration(n) && names.includes(n.name?.text));
  assert.equal(nodes.length, names.length, filename);
  selections.push({version, file, names, source_sha256: sha(source),
    selected_sha256: sha(nodes.map(n => n.getText(parsed)).join('\n'))});
  return nodes.map(n => n.getText(parsed)).join('\n');
}
function load(version, current) {
  let source = declarations(version, 'runner.ts', ['executeStep','extractErrorData','getNextStepPreview']);
  for (const [file,names] of [
    ['mcp.ts',['callMCPToolImpl','callMCPToolRawImpl']],
    ['client.ts',['runStep']],
    ['task-map.ts',['executeStoryboardTask']],
    ['context.ts',['injectContext','deepReplace','extractContext']],
    ['path.ts',['parsePath','resolvePath']],
    ['validations.ts',['runValidations','runValidation','validateFieldPresent','validateFieldValue','valuesMatch']],
    ['test-controller.ts',['controllerError','summarize','toMcpResponse']],
    ['responses.ts',['toStructuredContent']],
  ]) source += '\n' + declarations('after', file, names);
  // Original constant maps are not needed for comply_test_controller: the
  // pinned maps contain no entry for that task. Fail if this assumption changes.
  for (const file of ['task-map.ts','context.ts']) {
    assert(!fs.readFileSync(path.join(OUT,'sources/adcp-after',file),'utf8').includes('comply_test_controller'));
  }
  const unexpected = () => {throw new Error('Unexpected unexercised collaborator');};
  const sandbox = {exports:{}, console, Error, Date, setTimeout,
    TASK_TO_METHOD:{}, CONTEXT_EXTRACTORS:{},
    hasRequestBuilder:()=>false, buildRequest:unexpected,
    applyContextInputs:unexpected, applyContextOutputs:unexpected,
    validateResponseSchema:unexpected, validateStatusCode:unexpected, validateErrorCode:unexpected,
    injectTraceHeaders:()=>({}), createMCPAuthHeaders:unexpected,
    withCachedConnection:async (_url,_token,_headers,_logs,name,callback)=>{
      assert.equal(name,'comply_test_controller');
      return callback({callTool:async ()=>clone(current.response)});
    },
  };
  const context = vm.createContext(sandbox);
  const compiled = ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}});
  vm.runInContext(compiled.outputText,context,{filename:'pinned-adcp-'+version+'.js'});
  return context;
}
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([key])=>key!=='duration_ms').map(([key,val])=>[key,stable(val)]));
  return value;
}
async function main() {
  const steps = JSON.parse(fs.readFileSync(path.join(OUT,'adcp-original-steps.json')));
  const rows = [];
  for (const version of ['before','after']) {
    const current = {};
    const ctx = load(version,current);
    for (const route of ['flattened_error','raw_data_control']) {
      // TaskExecutor behavior is controlled, not executed: catch the native
      // MCP exception into a failed TaskResult without data as in issue464.
      const client = {executeTask:async (name,args)=>{
        try {
          const response = await ctx[route==='flattened_error'?'callMCPToolImpl':'callMCPToolRawImpl']('https://fixture.invalid',name,args);
          return {success:!response.isError,data:response.structuredContent};
        } catch(error) {return {success:false,error:error.message};}
      }};
      for (const step of steps) {
        const code = step.validations.find(v=>v.path==='error').allowed_values[0];
        for (const detail of ['Original detail A: account alpha is unavailable','Original detail B: creative beta was removed']) {
          const payload = ctx.controllerError(code,detail);
          current.response = clone(ctx.toMcpResponse(payload));
          const output = stable(await ctx.executeStep(client,clone(step),'controller',{},[],{}));
          const row = {version,route,step_id:step.id,code,original_detail:detail,
            input:clone(current.response),output:clone(output),
            original_validations_pass:output.passed,
            original_detail_retained:output.response?.error_detail===detail,
            code_retained:output.response?.error===code,
            detail_field_present:typeof output.response?.error_detail==='string'};
          assert.equal(row.original_validations_pass,route==='raw_data_control'||version==='after');
          assert.equal(row.original_detail_retained,route==='raw_data_control');
          rows.push(row);
        }
      }
      const source = {success:true,simulated:{spend_percentage:25}};
      current.response=clone(ctx.toMcpResponse(source));
      const step={id:'success_control',title:'Success control',task:'comply_test_controller',sample_request:{scenario:'simulate_budget_spend'},validations:[{check:'field_value',path:'success',allowed_values:[true],description:'Success remains true'}]};
      const output=stable(await ctx.executeStep(client,step,'controller',{},[],{}));
      assert(output.passed);
      assert.deepStrictEqual(clone(output.response),source);
      rows.push({version,route,step_id:step.id,input:clone(current.response),output:clone(output)});
    }
  }
  const comparisons=[];
  for(const version of ['before','after']) for(const route of ['flattened_error','raw_data_control']) for(const step of steps){
    const pair=rows.filter(r=>r.version===version&&r.route===route&&r.step_id===step.id);
    const same=JSON.stringify(pair[0].output)===JSON.stringify(pair[1].output);
    assert.equal(same,route==='flattened_error');
    comparisons.push({version,route,step_id:step.id,paired_details_same_output:same});
  }
  const report={protocol:'research/mcp-adcp-reconstruction-amendment.json',
    rows,comparisons,source_selections:selections,node:process.version,typescript:ts.version,
    boundary:'Unchanged native TS function bodies transpiled by TypeScript. Native server response construction, MCP error flattening, storyboard runner and field validators; controlled connection and TaskExecutor return shape. No HTTP transport or complete SDK deployment.',
    held_fixed:'After-version producer, MCP functions, task dispatcher, context helpers and validators are shared across the two runner versions. The before/after MCP files are byte-identical. This isolates runner reconstruction; not two complete historical releases.',
    limits:['Three original YAML error steps and their six field assertions are unchanged; paired error details and success control are authored.','The raw-data route is a diagnostic control with an authored TaskResult mapping, not a validated full-system patch.','The original assertions require success=false and the error code, not exact original detail. Passing after repair is correct for that narrower obligation.','Only duration_ms is excluded from deterministic output comparisons.','No claim of production frequency, new upstream defect, or model accuracy.'],paid_calls:0};
  fs.writeFileSync(path.join(OUT,'adcp-reconstruction.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({cells:rows.length,comparisons,summary:rows.filter(r=>r.step_id!=='success_control').map(({version,route,step_id,original_validations_pass,original_detail_retained})=>({version,route,step_id,original_validations_pass,original_detail_retained}))},null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
