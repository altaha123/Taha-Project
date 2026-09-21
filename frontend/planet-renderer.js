/* True 3D ray/sphere and ray/ring intersections, rendered on the GPU.
   Surface maps: Solar System Scope / INOVE, CC BY 4.0; see assets/planets/CREDITS.md. */
(function () {
  'use strict';
  var root=new URL('assets/planets/',document.currentScript ? document.currentScript.src : document.baseURI);
  var maps=['jupiter','venus_atmosphere','saturn','mars','neptune','earth_daymap'];
  var vertex='attribute vec2 position; varying vec2 point; void main(){point=position*2.5;gl_Position=vec4(position,0.,1.);}';
  var fragment=`
precision highp float;
varying vec2 point;
uniform sampler2D surface;
uniform sampler2D rings;
uniform float rotation;
uniform float world;
uniform float loaded;
const vec3 sun=vec3(-0.66,0.38,0.65);
const vec3 ringNormal=vec3(0.16,0.88,0.447);
vec2 uv(vec3 n){
  if(world==2.){
    vec3 north=normalize(ringNormal),east=normalize(cross(north,vec3(0.,0.,1.)));
    n=vec3(dot(n,east),dot(n,north),dot(n,cross(east,north)));
  }
  float c=cos(rotation),s=sin(rotation);
  vec3 p=vec3(c*n.x+s*n.z,n.y,-s*n.x+c*n.z);
  return vec2(fract(atan(p.z,p.x)/6.2831853+0.5),0.5-asin(clamp(p.y,-1.,1.))/3.14159265);
}
float sphereHit(vec3 o,vec3 d){
  float b=dot(o,d),h=b*b-dot(o,o)+1.;
  if(h<0.)return -1.;
  float t=-b-sqrt(h);return t>0.?t:-1.;
}
vec4 ringMap(float r){
  if(r<1.24||r>2.27)return vec4(0.);
  return texture2D(rings,vec2((r-1.24)/1.03,0.5));
}
void main(){
  // Orthographic rays give a stable astronomical telephoto view of a 3D sphere.
  vec3 origin=vec3(point,6.),ray=vec3(0.,0.,-1.);
  float t=sphereHit(origin,ray);
  vec4 result=vec4(0.);
  if(t>0.){
    vec3 n=normalize(origin+ray*t);
    vec3 albedo=texture2D(surface,uv(n)).rgb;
    if(loaded<0.5)albedo=vec3(0.38,0.35,0.30);
    float diffuse=max(dot(n,sun),0.);
    float shadow=1.;
    if(world==2.){
      float rt=-dot(n,ringNormal)/dot(sun,ringNormal);
      if(rt>0.)shadow=1.-ringMap(length(n+sun*rt)).a*0.7;
    }
    vec3 linear=pow(albedo,vec3(2.2))*(0.018+diffuse*1.2*shadow);
    // Thin sunlit atmospheric limb, strongest on Earth and Neptune.
    vec3 air=world==5.?vec3(.16,.38,.7):world==4.?vec3(.10,.24,.55):vec3(.28,.20,.11);
    float rim=pow(1.-n.z,4.)*smoothstep(-.15,.4,dot(n,sun));
    linear+=air*rim*.22;
    result=vec4(pow(linear,vec3(1./2.2)),1.);
  }
  if(world==2.){
    float rt=-dot(origin,ringNormal)/dot(ray,ringNormal);
    vec3 p=origin+ray*rt;
    vec4 ring=ringMap(length(p));
    if(rt>0.&&(t<0.||rt<t)&&ring.a>0.){
      float shadow=sphereHit(p+sun*.005,sun)>0.?0.12:1.;
      vec3 color=pow(pow(ring.rgb,vec3(2.2))*(.16+.85*shadow),vec3(1./2.2));
      float alpha=ring.a+result.a*(1.-ring.a);
      result=vec4((color*ring.a+result.rgb*result.a*(1.-ring.a))/max(alpha,.001),alpha);
    }
  }
  gl_FragColor=result;
}`;
  function create(onReady){
    var canvas=document.createElement('canvas'),gl;
    try{gl=canvas.getContext('webgl',{alpha:true,premultipliedAlpha:false,antialias:true,preserveDrawingBuffer:true});}catch(_){return null;}
    if(!gl)return null;
    var program,buffer,shaders=[],textures=[],images=[],dead=false,lost=false;
    function compile(type,source){
      var s=gl.createShader(type);shaders.push(s);gl.shaderSource(s,source);gl.compileShader(s);
      if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;
    }
    function dispose(){
      if(dead)return;dead=true;
      images.forEach(function(i){i.onload=i.onerror=null;});
      textures.forEach(function(t){gl.deleteTexture(t.texture);});
      shaders.forEach(function(s){gl.deleteShader(s);});
      if(buffer)gl.deleteBuffer(buffer);if(program)gl.deleteProgram(program);
      canvas.removeEventListener('webglcontextlost',contextLost);
      canvas.removeEventListener('webglcontextrestored',contextRestored);
    }
    function contextLost(e){e.preventDefault();lost=true;if(onReady)onReady();}
    // The owning voyage replaces this renderer after restoration.
    function contextRestored(){if(onReady)onReady(true);}
    try{
      program=gl.createProgram();gl.attachShader(program,compile(gl.VERTEX_SHADER,vertex));gl.attachShader(program,compile(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);
      if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program));
      gl.useProgram(program);buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
      gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
      var position=gl.getAttribLocation(program,'position');gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
    }catch(_){dispose();return null;}
    var uniforms={};['surface','rings','rotation','world','loaded'].forEach(function(n){uniforms[n]=gl.getUniformLocation(program,n);});
    function texture(name,ring){
      var item={texture:gl.createTexture(),ready:false};textures.push(item);
      gl.bindTexture(gl.TEXTURE_2D,item.texture);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array(ring?[175,157,128,190]:[150,139,125,255]));
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      var img=new Image();images.push(img);
      img.onload=function(){
        if(dead||lost)return;
        gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,item.texture);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,img);item.ready=true;if(onReady)onReady();
      };
      img.onerror=function(){if(!dead&&onReady)onReady();};
      img.src=new URL(name+(ring?'.png':'.jpg'),root).href;return item;
    }
    var surfaces=maps.map(function(n){return texture(n,false);}),ring=texture('saturn_ring_alpha',true);
    canvas.addEventListener('webglcontextlost',contextLost);canvas.addEventListener('webglcontextrestored',contextRestored);
    return {
      render:function(index,time,size){
        if(dead||lost||gl.isContextLost())return null;
        // Fixed quality tiers prevent drawing-buffer reallocations during zoom.
        var target=size>700?1024:512;
        if(canvas.width!==target){canvas.width=canvas.height=target;gl.viewport(0,0,target,target);}
        gl.useProgram(program);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
        gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,surfaces[index].texture);gl.uniform1i(uniforms.surface,0);
        gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,ring.texture);gl.uniform1i(uniforms.rings,1);
        gl.uniform1f(uniforms.rotation,time*.10);gl.uniform1f(uniforms.world,index);gl.uniform1f(uniforms.loaded,surfaces[index].ready?1:0);
        gl.drawArrays(gl.TRIANGLES,0,6);return canvas;
      },
      destroy:dispose
    };
  }
  window.AltahaPlanets={create:create};
})();
