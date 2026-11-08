'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="console-token"]').content;
let before, after, diff, original, modified, removed, added;
let files=[], filePath='', selected='', current=null, config={}, busy=false, polling=false;

async function api(path,data) {
  const response=await fetch(path,{method:data?'POST':'GET',headers:{'X-Console-Token':token,...(data?{'Content-Type':'application/json'}:{})},body:data?JSON.stringify(data):undefined});
  const result=await response.json();if(!response.ok)throw Error(result.error||'请求失败');return result;
}
function fail(error){$('error').hidden=false;$('error').textContent=error.message||String(error);}
function controls(){
  $('start').disabled=busy||Boolean(current?.running);
  $('kill').disabled=busy||!current?.running;
  $('resume').disabled=busy||!current||current.running||['completed','baseline_failed'].includes(current.phase);
}
function highlight(){
  const changes=diff.getLineChanges()||[];
  const decorations=(side,cls)=>changes.filter(c=>c[side+'EndLineNumber']>0).map(c=>({
    range:new monaco.Range(c[side+'StartLineNumber'],1,c[side+'EndLineNumber'],1),
    options:{isWholeLine:true,className:'diff-'+cls,linesDecorationsClassName:'diff-gutter-'+cls}
  }));
  removed.set(decorations('original','removed'));added.set(decorations('modified','added'));
}
function showFile(path){
  const file=files.find(f=>f.path===path);if(!file||!original)return;
  const switched=filePath!==path;filePath=path;$('files').value=path;
  if(original.getValue()!==file.before){removed.clear();original.setValue(file.before);}
  if(modified.getValue()!==file.after){added.clear();modified.setValue(file.after);}
  if(switched){before.setScrollTop(0);after.setScrollTop(0);}
}
function updateFiles(next){
  files=next;const options=$('files');const paths=files.map(f=>f.path);
  if(JSON.stringify([...options.options].map(o=>o.value))!==JSON.stringify(paths))options.replaceChildren(...paths.map(p=>new Option(p,p)));
  showFile(paths.includes(filePath)?filePath:(files.find(f=>f.path==='legacy_orders.py')||files[0])?.path);
}
function render(state){
  current=state;controls();updateFiles(state.files);
  if(state.error)fail(state.error.message);
}
async function refresh(){if(selected)render(await api('/api/run/'+selected));}
async function act(action){
  if(busy)return;busy=true;controls();$('error').hidden=true;
  try{
    const data=action==='start'?{...config,action:'start',provider:config.provider||'mock',stop_after:config.stop_after??true}:{action,id:selected};
    const result=await api('/api/action',data);selected=result.id||selected;
    localStorage.setItem('continuum-minimal-run',selected);await refresh();
  }catch(error){fail(error);}finally{busy=false;controls();}
}
for(const action of ['start','kill','resume'])$(action).onclick=()=>act(action);
$('files').onchange=()=>showFile($('files').value);

if(!window.require)fail('Monaco 加载失败');
else{
  require.config({paths:{vs:'/vendor/monaco/vs'}});
  require(['vs/editor/editor.main'],async()=>{
    monaco.editor.defineTheme('continuum-warm',{base:'vs',inherit:true,rules:[
      {token:'comment',foreground:'AAA18F',fontStyle:'italic'},
      {token:'keyword',foreground:'B57142'},
      {token:'string',foreground:'8B8960'},
      {token:'number',foreground:'B17A51'}
    ],colors:{'editor.background':'#FFFDF8','editor.foreground':'#635547','editorLineNumber.foreground':'#CCBFAE','editorLineNumber.activeForeground':'#A18B72','editor.lineHighlightBackground':'#FFFDF8','editor.selectionBackground':'#EADAC6','editor.inactiveSelectionBackground':'#F1E6D8','editorCursor.foreground':'#C77C48','editorGutter.background':'#FFFDF8','editorIndentGuide.background1':'#F1E9DE','scrollbarSlider.background':'#D6C8B655','scrollbarSlider.hoverBackground':'#D6C8B6AA','editorWidget.background':'#FFFDF8'}});
    const options={theme:'continuum-warm',automaticLayout:true,readOnly:true,fontSize:13,lineHeight:23,fontFamily:'Consolas, "Courier New", monospace',minimap:{enabled:false},scrollBeyondLastLine:false,renderLineHighlight:'none',overviewRulerLanes:0,hideCursorInOverviewRuler:true,folding:false,lineNumbersMinChars:3,glyphMargin:false,lineDecorationsWidth:14,padding:{top:20,bottom:20},scrollbar:{verticalScrollbarSize:5,horizontalScrollbarSize:5},contextmenu:false};
    original=monaco.editor.createModel('','python');modified=monaco.editor.createModel('','python');
    before=monaco.editor.create($('before'),{...options,model:original});after=monaco.editor.create($('after'),{...options,model:modified});
    removed=before.createDecorationsCollection();added=after.createDecorationsCollection();
    diff=monaco.editor.createDiffEditor($('diff-engine'),{readOnly:true,renderSideBySide:true,automaticLayout:false});
    diff.setModel({original,modified});diff.onDidUpdateDiff(highlight);
    let scrolling=false;
    for(const [a,b] of [[before,after],[after,before]])a.onDidScrollChange(e=>{if(scrolling)return;scrolling=true;b.setScrollTop(e.scrollTop);b.setScrollLeft(e.scrollLeft);scrolling=false;});
    try{
      const demo=await api('/api/demo');config=demo.config;updateFiles(demo.files);
      const saved=localStorage.getItem('continuum-minimal-run');if(saved){try{const run=await api('/api/run/'+saved);selected=saved;render(run);}catch{localStorage.removeItem('continuum-minimal-run');}}
    }catch(error){fail(error);}
    setInterval(async()=>{if(polling||busy||!selected)return;polling=true;try{await refresh();}catch(error){fail(error);}finally{polling=false;}},1500);
  },fail);
}
