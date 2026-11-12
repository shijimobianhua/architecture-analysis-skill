#target photoshop
/* Import aligned PNGs without clipboard/Place scaling. Does not modify existing docs. */
(function () {
 function parseJSON(s) {
  var i=0;
  function ws(){while(/\s/.test(s.charAt(i))&&i<s.length)i++;}
  function str(){var start=i++;while(i<s.length){var c=s.charAt(i++);if(c==='"'){var raw=s.substring(start,i);return decode(raw);}if(c==='\\')i++;}throw Error('Unclosed string');}
  function decode(raw){return raw.substring(1,raw.length-1).replace(/\\(?:u([a-fA-F0-9]{4})|(["\\\/bfnrt]))/g,function(_,u,c){if(u)return String.fromCharCode(parseInt(u,16));var m={'b':'\b','f':'\f','n':'\n','r':'\r','t':'\t'};return m[c]!==undefined?m[c]:c;});}
  function val(){ws();var c=s.charAt(i),out,k;
   if(c==='"')return str();
   if(c==='{'){i++;out={};ws();if(s.charAt(i)==='}'){i++;return out;}while(true){ws();if(s.charAt(i)!=='"')throw Error('Invalid key');k=str();ws();if(s.charAt(i++)!==':')throw Error('Expected colon');if(k==='__proto__'||k==='constructor'||k==='prototype')throw Error('Invalid key');out[k]=val();ws();c=s.charAt(i++);if(c==='}')return out;if(c!==',')throw Error('Expected comma');}}
   if(c==='['){i++;out=[];ws();if(s.charAt(i)===']'){i++;return out;}while(true){out.push(val());ws();c=s.charAt(i++);if(c===']')return out;if(c!==',')throw Error('Expected comma');}}
   var rest=s.substring(i),m=/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(rest);if(m){i+=m[0].length;return Number(m[0]);}
   var literals=['true','false','null'];for(var n=0;n<3;n++){if(rest.indexOf(literals[n])===0){i+=literals[n].length;return n===0?true:n===1?false:null;}}throw Error('Invalid JSON');
  }
  var result=val();ws();if(i!==s.length)throw Error('Unexpected JSON tail');return result;
 }
 function read(file){file.encoding='UTF8';if(!file.open('r'))throw Error('Cannot read '+file.fsName);var s=file.read();file.close();return s.replace(/^\uFEFF/,'');}
 function output(file,s){file.encoding='UTF8';if(!file.open('w'))throw Error('Cannot write report');file.write(s);file.close();}
 function px(v){return Number(v.as('px'));}
 function box(layer){var b=layer.bounds;return [px(b[0]),px(b[1]),px(b[2]),px(b[3])];}
 var test=typeof ARCH_ANALYSIS_TEST_FOLDER!=='undefined';
 var folder=test?Folder(ARCH_ANALYSIS_TEST_FOLDER):Folder.selectDialog('选择包含 manifest.json 的分层PNG交付目录');if(!folder)return;
 var manifest=parseJSON(read(File(folder.fsName+'/manifest.json'))),c=manifest.canvas,entries=manifest.layers;
 if(!entries||!entries.length||manifest.blend!=='normal'||manifest.opacity!==100||entries[0].role!=='background')throw Error('Unsupported layer manifest');
 function fileAt(name){if(/(^[\\\/]|:|(^|[\\\/])\.\.([\\\/]|$))/.test(name))throw Error('Invalid layer filename');var f=File(folder.fsName+'/'+name);if(!f.exists)throw Error('Missing '+name);return f;}
 var units=app.preferences.rulerUnits,dialogs=app.displayDialogs,target=null,src=null,rows=[],temps=[];
 function openFresh(file){var tmp=File(Folder.temp.fsName+'/architecture-analysis-'+new Date().getTime()+'-'+Math.floor(Math.random()*1000000)+'.png');if(!file.copy(tmp.fsName))throw Error('Cannot copy input');temps.push(tmp);return app.open(tmp);}
 try{
  app.preferences.rulerUnits=Units.PIXELS;app.displayDialogs=DialogModes.NO;
  for(var j=0;j<entries.length;j++){
   src=openFresh(fileAt(entries[j].file));
   if(px(src.width)!==c.width||px(src.height)!==c.height||Math.abs(src.resolution-c.dpi)>.1)throw Error('Layer canvas or resolution mismatch');
   if(j===0){target=src;src=null;target.activeLayer.name=entries[j].name;}
   else{
    var original=box(src.activeLayer),copy=src.activeLayer.duplicate(target,ElementPlacement.PLACEATBEGINNING);
    src.close(SaveOptions.DONOTSAVECHANGES);src=null;app.activeDocument=target;target.activeLayer=copy;
    var placed=box(copy);copy.translate(original[0]-placed[0],original[1]-placed[1]);copy.name=entries[j].name;copy.blendMode=BlendMode.NORMAL;copy.opacity=100;
    var after=box(copy);if(Math.abs(after[0]-original[0])>.01||Math.abs(after[1]-original[1])>.01)throw Error('Alignment failed');
   }
   rows.push(entries[j].file+'\t'+box(target.activeLayer).join(','));
  }
  if(test){var png=new PNGSaveOptions();png.interlaced=false;target.saveAs(File(folder.fsName+'/ps-roundtrip.png'),png,true,Extension.LOWERCASE);output(File(folder.fsName+'/ps-report.tsv'),'version\t'+app.version+'\ncanvas\t'+px(target.width)+','+px(target.height)+'\nlayers\t'+target.layers.length+'\n'+rows.join('\n'));}
  else alert('已按原画布坐标导入 '+entries.length+' 层。文字为PNG栅格层。');
 }finally{if(src)src.close(SaveOptions.DONOTSAVECHANGES);app.preferences.rulerUnits=units;app.displayDialogs=dialogs;for(var ti=0;ti<temps.length;ti++)if(temps[ti].exists)temps[ti].remove();}
})();

