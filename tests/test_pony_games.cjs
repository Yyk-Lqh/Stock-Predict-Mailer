const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({});
vm.runInContext(fs.readFileSync('src/stock_predict_mailer/control/web/modules/pony-screen.js','utf8'),context);
const {simulate,render,games}=context.PonyScreen;
const equal=(a,b,message)=>assert.deepEqual(JSON.parse(JSON.stringify(a)),JSON.parse(JSON.stringify(b)),message);
for(const mode of games){
  equal(simulate(mode,8,2),simulate(mode,8,2),`${mode} repeats deterministically`);
  assert.notDeepEqual(JSON.parse(JSON.stringify(simulate(mode,8,2))),JSON.parse(JSON.stringify(simulate(mode,8,5))),`${mode} differs by pony seed`);
  assert.notDeepEqual(JSON.parse(JSON.stringify(simulate(mode,8,2))),JSON.parse(JSON.stringify(simulate(mode,12,2))),`${mode} advances over time`);
}
for(let time=0;time<40;time+=.23){
  const snake=simulate(games[0],time,2);
  assert.ok(snake.body.length>=6);
  assert.equal(snake.score,snake.body.length-6,'snake grows only after eating food');
  for(let i=1;i<snake.body.length;i++) assert.equal(Math.abs(snake.body[i].x-snake.body[i-1].x)+Math.abs(snake.body[i].y-snake.body[i-1].y),1,`snake body is contiguous at ${time}s`);
  assert.ok(!snake.body.some(p=>p.x===snake.food.x&&p.y===snake.food.y),'food never overlaps snake');
}
const mine=simulate(games[1],8,2), index=(x,y)=>y*mine.width+x;
assert.equal(mine.mines.length,7);
assert.equal(new Set(mine.mines).size,7,'mine locations are unique');
assert.ok(mine.cells.filter(cell=>cell.revealed).every(cell=>!cell.mine),'automatic mine sweep never reveals a mine');
for(const cell of mine.cells) if(cell.revealed&&!cell.mine){
  let adjacent=0;
  for(let y=Math.max(0,cell.y-1);y<=Math.min(mine.height-1,cell.y+1);y++) for(let x=Math.max(0,cell.x-1);x<=Math.min(mine.width-1,cell.x+1);x++) if((x!==cell.x||y!==cell.y)&&mine.mines.includes(index(x,y))) adjacent++;
  assert.equal(cell.number,adjacent,'revealed mine count matches the board');
}
for(const cell of mine.cells) if(!cell.mine){
  let adjacent=0;
  for(let y=Math.max(0,cell.y-1);y<=Math.min(mine.height-1,cell.y+1);y++) for(let x=Math.max(0,cell.x-1);x<=Math.min(mine.width-1,cell.x+1);x++) if((x!==cell.x||y!==cell.y)&&mine.mines.includes(index(x,y))) adjacent++;
  assert.equal(cell.number,adjacent,'every mine count matches the board');
}
for(let time=0;time<33;time+=.7){
  const tetris=simulate(games[2],time,2),occupied=new Set(tetris.board.map(cell=>`${cell.x},${cell.y}`));
  assert.ok(tetris.board.length>=4,'tetris scene includes settled blocks');
  assert.equal(occupied.size,tetris.board.length,'settled blocks do not overlap');
  for(const {x,y} of tetris.piece.cells){
    assert.ok(x>=0&&x<tetris.width&&y>=0&&y<tetris.height,'falling piece stays on board');
    assert.ok(!occupied.has(`${x},${y}`),'falling piece does not overlap settled blocks');
  }
}
const ball=simulate(games[3],19,2);
assert.ok(ball.ball.x>=2&&ball.ball.x<=94&&ball.ball.y>=11&&ball.ball.y<=53,'ball remains in playfield');
assert.ok(ball.score>0,'ball collision clears a brick');
assert.ok(ball.lives>=0&&ball.lives<=3,'misses consume lives before a new round');
const solvedMine=simulate(games[1],28,2);
assert.equal(solvedMine.flagged,4,'mines are flagged after safe tiles are swept');
const drawing=simulate(games[4],8,2);
assert.ok(drawing.points.length>10&&drawing.points.length<=48);
assert.ok(drawing.points.every(p=>p.x>=8&&p.x<=88&&p.y>=12&&p.y<=54));
assert.equal(simulate('unknown',2,1),null);
assert.equal(simulate(games[0],-2,1).tick,0);
const actor={id:'main',seed:2,color:'#f00',state:'idle',present:true,pose:'seated',activity:0,idleClock:8,feedbackUntil:0};
for(let activity=0;activity<games.length;activity++){
  actor.activity=activity;
  const screen=render(actor,8);
  assert.equal(screen.mode,games[activity]);
  assert.ok(screen.markup.includes('<svg')===false,'screen renderer returns inline SVG contents only');
  assert.ok(screen.markup.includes('translate(-48 -116)'));
  const attr=(tag,name)=>Number(new RegExp(`${name}="([^"]+)"`).exec(tag)?.[1]);
  for(const tag of screen.markup.match(/<rect\b[^>]*\/>/g)||[]){
    const x=attr(tag,'x'),y=attr(tag,'y'),width=attr(tag,'width'),height=attr(tag,'height');
    assert.ok(x>=0&&y>=0&&x+width<=96&&y+height<=58,`${games[activity]} rectangle remains on screen`);
  }
  for(const tag of screen.markup.match(/<circle\b[^>]*\/>/g)||[]){
    const cx=attr(tag,'cx'),cy=attr(tag,'cy'),radius=attr(tag,'r');
    assert.ok(cx-radius>=0&&cy-radius>=0&&cx+radius<=96&&cy+radius<=58,`${games[activity]} circle remains on screen`);
  }
  for(const tag of screen.markup.match(/<text\b[^>]*>/g)||[]){
    assert.ok(attr(tag,'x')>=0&&attr(tag,'x')<=96&&attr(tag,'y')>=0&&attr(tag,'y')<=58,`${games[activity]} label anchor remains on screen`);
  }
  for(const tag of screen.markup.match(/<polyline\b[^>]*>/g)||[]){
    const points=/points="([^"]+)"/.exec(tag)[1].split(' ').map(p=>p.split(',').map(Number));
    assert.ok(points.every(([x,y])=>x>=0&&x<=96&&y>=0&&y<=58),'drawing path remains on screen');
  }
}
actor.activity=0;
actor.state='running'; actor.taskLabel='财报分析';
assert.equal(render(actor,9).mode,'task'); assert.ok(render(actor,9).markup.includes('财报分析'));
assert.equal(render(actor,9,false).mode,'disconnected');
for(const [status,label] of [['completed','已完成'],['failed','失败'],['canceled','已取消']]){
  actor.state=status; actor.feedbackUntil=20;
  assert.equal(render(actor,10).mode,'result'); assert.ok(render(actor,10).markup.includes(label),`${status} has explicit screen feedback`);
}
actor.state='idle'; actor.present=false;
assert.equal(render(actor,30).mode,'off');
console.log('Idle game rules passed: deterministic seeds, coherent snake and mine boards, bounded tetromino, brick collision, growing drawing, and task-screen priority.');
