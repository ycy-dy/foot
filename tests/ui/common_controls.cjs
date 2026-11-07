// Real app.js under a deterministic minimal DOM: no browser/network side effects.
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const callbacks = {}; const control = {disabled:false, dataset:{}, attrs:{}, setAttribute(k,v){this.attrs[k]=v}, removeAttribute(k){delete this.attrs[k]}};
let mirrored=[]; const form = {dataset:{}, attrs:{}, listeners:{}, addEventListener(k,f){this.listeners[k]=f},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},append(x){mirrored.push(x)},querySelectorAll(s){if(s==='[data-submitter-mirror]')return mirrored.map(x=>({...x,remove(){mirrored=[]}}));return [control]}};
const root={dataset:{}}; const theme={setAttribute(){},addEventListener(k,f){this[k]=f}};
const context={document:{documentElement:root,querySelector(s){return s==='[data-theme-toggle]'?theme:null},querySelectorAll(s){if(s==='form[method="post"]')return [form];if(s==='form[data-submitting="true"]')return form.dataset.submitting==='true'?[form]:[];return []},addEventListener(){},getElementById(){return {textContent:'',hidden:true}},createElement(){return {dataset:{}}}},window:{FOOT:{},matchMedia(){return {matches:false,addEventListener(){}}},addEventListener(k,f){callbacks[k]=f}},localStorage:{setItem(){}},location:{hash:''},setTimeout(){},clearTimeout(){}};
context.window.addEventListener=(k,f)=>callbacks[k]=f;
vm.runInNewContext(fs.readFileSync('src/foot_web/static/app.js','utf8'),context);
theme.click();assert.equal(root.dataset.theme,'dark');theme.click();assert.equal(root.dataset.theme,'light');
let prevented=0;const event={defaultPrevented:false,submitter:{name:'action',value:'publish'},preventDefault(){prevented++}};
form.listeners.submit(event);assert.equal(form.dataset.submitting,'true');assert.equal(control.disabled,true);assert.equal(mirrored[0].value,'publish');form.listeners.submit(event);assert.equal(prevented,1);
callbacks.pageshow();assert.equal(control.disabled,false);assert.equal(form.dataset.submitting,'false');assert.equal(mirrored.length,0);
console.log('Common controls: theme toggle, form duplicate lock, submitter preservation, back/forward unlock passed');
