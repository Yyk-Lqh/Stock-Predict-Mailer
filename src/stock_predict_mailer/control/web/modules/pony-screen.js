/* Small, deterministic idle simulations. They never submit tasks or call models. */
globalThis.PonyScreen = (() => {
  const games = ['贪吃蛇', '扫雷', '俄罗斯方块', '打砖块', '绘图'];
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const rect = (x,y,w,h,color) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="1" fill="${color}"/>`;
  const text = (x,y,value,color='#d9edf6',size=6) => `<text x="${x}" y="${y}" font-size="${size}" fill="${color}" font-family="sans-serif">${escape(value)}</text>`;
  function state(actor, time, connected = true) {
    if (actor.state === 'running') return connected ? 'task' : 'disconnected';
    if (time < actor.feedbackUntil) return 'result';
    if (!actor.present) return 'off';
    return actor.pose === 'seated' ? games[actor.activity % games.length] : 'screensaver';
  }
  const wrap=(n,size)=>(n%size+size)%size;
  const atRate=(time,perSecond)=>Math.floor(time*perSecond);
  const hash=(n,seed)=>{
    let value=(n+seed*0x9e3779b9+0x85ebca6b)>>>0;
    value=Math.imul(value^(value>>>16),0x7feb352d);
    value=Math.imul(value^(value>>>15),0x846ca68b);
    return(value^(value>>>16))>>>0;
  };
  function shuffled(values,seed){
    const result=values.slice();let state=(seed^0xa341316c)>>>0;
    for(let i=result.length-1;i>0;i--){
      state=(Math.imul(state,1664525)+1013904223)>>>0;
      const j=state%(i+1);[result[i],result[j]]=[result[j],result[i]];
    }
    return result;
  }
  function snake(time,seed){
    const width=13,height=7,perimeter=2*width+2*height-4,tick=atRate(time,1.8);
    const locate=k=>{k=wrap(k,perimeter);if(k<width)return{x:k+2,y:1};k-=width;if(k<height-1)return{x:width+1,y:k+2};k-=height-1;if(k<width-1)return{x:width-k,y:height};k-=width-1;return{x:2,y:height-1-k};};
    let headAt=wrap(seed*5,perimeter),length=6,score=0;
    const nextFood=()=>wrap(headAt+length+3+hash(score+1,seed)%10,perimeter);
    let foodAt=nextFood();
    for(let step=0;step<tick;step++){
      headAt=wrap(headAt+1,perimeter);
      if(headAt===foodAt){score++;length++;foodAt=nextFood();}
    }
    const body=Array.from({length},(_,i)=>locate(headAt-i));
    const next=locate(headAt+1),now=locate(headAt);
    return{tick,body,food:locate(foodAt),direction:{x:Math.sign(next.x-now.x),y:Math.sign(next.y-now.y)},score};
  }
  function minesweeper(time,seed){
    const width=9,height=5,total=width*height,centerSafe=i=>{
      const x=i%width,y=Math.floor(i/width);return Math.abs(x-4)>1||Math.abs(y-2)>1;
    };
    const candidate=shuffled(Array.from({length:total},(_,i)=>i).filter(centerSafe),seed),mines=candidate.slice(0,7),mineSet=new Set(mines);
    const tick=atRate(time,1.5),safeOrder=Array.from({length:total},(_,i)=>i).filter(i=>!mineSet.has(i)).sort((a,b)=>{
      const rank=i=>{const x=i%width,y=Math.floor(i/width);return Math.abs(x-4)+Math.abs(y-2);};return rank(a)-rank(b)||hash(a,seed+1)-hash(b,seed+1);
    });
    const cycleLength=safeOrder.length+mines.length,step=tick%cycleLength,revealCount=Math.min(step,safeOrder.length);
    const revealed=new Set(safeOrder.slice(0,revealCount)),flagCount=Math.max(0,step-safeOrder.length),flagged=new Set(shuffled(mines,seed+3).slice(0,flagCount));
    const cells=Array.from({length:total},(_,i)=>{const x=i%width,y=Math.floor(i/width);let number=0;
      for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++)if(dx||dy){const xx=x+dx,yy=y+dy;if(xx>=0&&xx<width&&yy>=0&&yy<height&&mines.includes(yy*width+xx))number++;}
      return{x,y,mine:mineSet.has(i),number,revealed:revealed.has(i),flag:flagged.has(i)};
    });
    return{width,height,mines,cells,revealed:revealCount,flagged:flagCount,tick};
  }
  function tetris(time,seed){
    const width=10,height=7,tick=atRate(time,2),cycle=tick%28,pieceNumber=Math.floor(tick/28);
    const shapes=[[[0,0],[0,1],[0,2],[0,3]],[[0,0],[1,0],[0,1],[1,1]],[[0,0],[1,0],[2,0],[1,1]],[[0,0],[0,1],[0,2],[1,2]]];
    const colors=['#e89ba7','#91d2bd','#e8be75','#a9afe8'],board=[];
    for(const x of [0,1,8,9])board.push({x,y:height-1,color:'#526b80'});
    const placed=new Set(board.map(cell=>`${cell.x},${cell.y}`));
    const shapeX=(shape,n)=>Math.min(width-1-Math.max(...shape.map(p=>p[0])),2+(seed+n)%4);
    const canPlace=(shape,x,y)=>shape.every(([dx,dy])=>x+dx>=0&&x+dx<width&&y+dy<height&&(y+dy<0||!placed.has(`${x+dx},${y+dy}`)));
    const landing=(shape,x)=>{let y=0;while(canPlace(shape,x,y+1))y++;return y;};
    for(let n=0;n<pieceNumber;n++){
      const shapeIndex=(seed+n)%shapes.length,shape=shapes[shapeIndex],x=shapeX(shape,n),y=landing(shape,x);
      for(const [dx,dy] of shape){const cell={x:x+dx,y:y+dy,color:colors[shapeIndex]};board.push(cell);placed.add(`${cell.x},${cell.y}`);}
    }
    const shapeIndex=(seed+pieceNumber)%shapes.length,shape=shapes[shapeIndex],x=shapeX(shape,pieceNumber),landingY=landing(shape,x);
    const fallY=Math.min(landingY,Math.floor(cycle/4)),cells=shape.map(([dx,dy])=>({x:x+dx,y:fallY+dy}));
    return{width,height,tick,board,piece:{cells,color:colors[shapeIndex]},score:pieceNumber*10,phase:cycle/28};
  }
  function breakout(time,seed){
    const bricks=Array.from({length:21},(_,i)=>({x:i%7,y:Math.floor(i/7),alive:true,color:['#94bedf','#cba4dc','#e5b07c'][i%3]}));
    let x=45+(seed%3)*3,y=43,vx=1.15+(seed%4)*.11,vy=-1.25,score=0,lives=3,wave=0;
    const frames=atRate(time,20);
    for(let frame=0;frame<frames;frame++){
      const oldY=y;x+=vx;y+=vy;
      if(x<3||x>93){vx=-vx;x=Math.max(3,Math.min(93,x));}
      if(y<11){vy=Math.abs(vy);y=11;}
      if(vy>0&&y>=49&&oldY<50){const paddle=47+Math.sin(frame*.012+seed)*23;if(Math.abs(x-paddle)<13){vy=-Math.abs(vy);vx+=(x-paddle)*.035;y=49;}}
      if(vy<0){const col=Math.floor((x-8)/12),row=Math.floor((y-13)/6),brick=bricks.find(b=>b.alive&&b.x===col&&b.y===row);
        if(brick){brick.alive=false;score++;vy=Math.abs(vy);y+=1;}}
      if(y>54){
        lives--;
        if(lives===0){lives=3;score=0;wave++;for(const brick of bricks)brick.alive=true;}
        x=45+(seed%3)*3;y=43;vx=1.15+(seed%4)*.11;vy=-1.25;
      }
    }
    return{ball:{x,y},velocity:{x:vx,y:vy},paddle:{x:47+Math.sin(frames*.012+seed)*23},bricks,score,lives,wave,tick:frames};
  }
  function drawing(time,seed){
    const ticks=atRate(time,4),count=Math.min(48,ticks+1),points=Array.from({length:count},(_,i)=>({x:12+(i*2.7)%72,y:32+Math.sin(i*.42+seed*.7)*11+Math.cos(i*.17+seed)*4}));
    return{points,stroke:['#df7887','#659783','#8270bd','#648fc2','#389990','#ae8842','#ad704f'][seed%7],tick:ticks};
  }
  function simulate(mode,time,seed=0){
    time=Math.max(0,Number.isFinite(time)?time:0);seed=Math.abs(Math.floor(seed||0));
    if(mode===games[0])return snake(time,seed);
    if(mode===games[1])return minesweeper(time,seed);
    if(mode===games[2])return tetris(time,seed);
    if(mode===games[3])return breakout(time,seed);
    if(mode===games[4])return drawing(time,seed);
    return null;
  }
  function render(actor, time, connected = true) {
    const mode = state(actor, time, connected), t = actor.idleClock || 0, localTime=t%33, seed = actor.seed;
    let content = '', title = mode;
    if (mode === 'off') return {mode, markup: '', title: '离室待机'};
    if (['task','disconnected','result'].includes(mode)) {
      const labels = {completed:'已完成', failed:'失败', canceled:'已取消', simulated:'模拟投递', submitted:'已提交', retry:'等待重试', uncertain:'结果待确认'};
      title = mode === 'disconnected' ? '连接中断 · 保留进度' : mode === 'result' ? labels[actor.state] || actor.state : actor.taskLabel || '执行任务';
      content = text(5,10,title.slice(0,15),mode === 'result' && actor.state === 'failed' ? '#ffa2a2' : '#9ee7cc');
      content += text(5,23,(actor.last || '等待下一步').slice(0,15));
      content += text(5,35,`已完成 ${actor.completedSteps || 0} 步 · ${Math.floor(actor.elapsed || 0)}s`);
      content += text(5,48,actor.childId ? `子任务 ${actor.childId.slice(0,9)}` : actor.taskId ? actor.taskId.slice(0,14) : '本地反馈');
      // No fabricated percentage: the backend currently exposes phases, not a fixed total.
      if (mode === 'task') content += rect(5,53,86,2,'#365368');
    } else if (mode === 'screensaver') {
      const phase = (time + seed * 9) / 35, blend = (Math.sin(phase * Math.PI) + 1) / 2;
      content = `<g opacity="${blend.toFixed(2)}">${text(22,31,`${String(Math.floor(time/60)%24).padStart(2,'0')}:${String(Math.floor(time)%60).padStart(2,'0')}`, '#9ccadf',14)}</g>`;
      content += `<g opacity="${(1-blend).toFixed(2)}">`;
      for(let i=0;i<7;i++) content += rect((i*19+time*(2+seed*.2))%90,18+Math.sin(time*.4+i)*13,5,5,['#a7c4ea','#dfbceb','#a7ded0'][i%3]);
      content += '</g>';
      title = '在室 · 动态屏保';
    } else {
      content = text(3,8,mode,'#accbde');
      const scene=simulate(mode,localTime,seed);
      if(mode === games[0]) {
        scene.body.forEach((p,i)=>content+=`<rect class="pony-screen-snake ${i?'snake-body':'snake-head'}" x="${8+p.x*5}" y="${12+p.y*5}" width="4.4" height="4.4" rx="1" fill="${i?'#72c79d':'#d5f7ab'}"/>`);
        content += rect(8+scene.food.x*5,12+scene.food.y*5,4.4,4.4,'#ef9298');
        content += text(70,9,`×${scene.score}`,'#d9edf6',5);
      } else if(mode === games[1]) {
        for(const cell of scene.cells){const x=11+cell.x*8,y=12+cell.y*8;content+=rect(x,y,7,7,cell.revealed?'#a9bbc4':'#526b80');
          if(cell.revealed&&cell.mine)content+=`<circle cx="${x+3.5}" cy="${y+3.5}" r="2.1" fill="#252e37"/>`;
          else if(cell.revealed&&cell.number)content+=text(x+2,y+6,cell.number,['','#426eaf','#519970','#cb8857','#a577b2'][cell.number]||'#d06c6c',6);
          else if(cell.flag)content+=text(x+1,y+6,'⚑','#f1bc86',6);
        }
      } else if(mode === games[2]) {
        content+=rect(21,12,52,38,'#122437');
        for(const cell of scene.board)content+=rect(23+cell.x*5,14+cell.y*5,4.5,4.5,cell.color);
        for(const cell of scene.piece.cells)content+=`<rect x="${23+cell.x*5}" y="${14+cell.y*5}" width="4.5" height="4.5" rx=".7" fill="${scene.piece.color}"/>`;
        content+=text(76,17,`S${scene.score}`,'#d9edf6',5);
      } else if(mode === games[3]) {
        for(const brick of scene.bricks)if(brick.alive)content+=rect(9+brick.x*12,13+brick.y*5,10,3.5,brick.color);
        content += rect(scene.paddle.x-10,50,20,2.5,'#b1ddd1');
        content += `<circle cx="${scene.ball.x.toFixed(1)}" cy="${scene.ball.y.toFixed(1)}" r="1.8" fill="#fff"/>`;
        content+=text(75,54,`${scene.score}`,'#d9edf6',5);
      } else {
        content += rect(8,12,80,42,'#eee9df');
        const trail=scene.points.map(p=>`${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
        content+=`<polyline points="${trail}" fill="none" stroke="${scene.stroke}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`;
        const cursor=scene.points[scene.points.length-1];content+=`<circle cx="${cursor.x.toFixed(1)}" cy="${cursor.y.toFixed(1)}" r="2" fill="#46536a"/>`;
      }
    }
    return {mode, title, markup:`<g transform="translate(-48 -116)">${rect(0,0,96,58,'#192d40')}${content}</g>`};
  }
  return {state, render, games, simulate};
})();
