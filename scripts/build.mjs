import {cp,mkdir,writeFile} from 'node:fs/promises';
await mkdir('public',{recursive:true});
await cp('web','public',{recursive:true});
await writeFile('public/runtime-config.js','window.LUME_CLOUD = true;\n');
console.log('Lume: interfaccia online preparata.');
