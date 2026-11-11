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
  function render(actor, time, connected = true) {
    const mode = state(actor, time, connected), t = actor.idleClock || 0, frame = Math.floor(t * 3), seed = actor.seed;
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
      if(mode === games[0]) {
        for(let i=0;i<8;i++) content += rect(5+((frame+i)%17)*5,20+Math.floor((frame+i)/17)%4*6,4,4,i===7?'#d5f7ab':'#72c79d');
        content += rect(75,43,4,4,'#ef9298');
      } else if(mode === games[1]) {
        for(let i=0;i<45;i++) {
          const x=13+i%9*8,y=12+Math.floor(i/9)*8, open=(i+seed)%45 < frame%46;
          content += rect(x,y,7,7,open?'#a9bbc4':'#526b80');
          if(open && i%3) content += text(x+2,y+6,i%3,'#243b65');
          if(!open && i%11===0) content += text(x+1,y+6,'⚑','#f1bc86');
        }
      } else if(mode === games[2]) {
        for(let i=0;i<24;i++) if((i+seed)%5) content += rect(25+i%6*6,49-Math.floor(i/6)*6,5,5,['#8fcaca','#ddc181','#bda1da'][i%3]);
        for(const [x,y] of [[0,0],[1,0],[1,1],[2,1]]) content += rect(31+x*6,12+(frame%6)*4+y*6,5,5,'#e89ba7');
      } else if(mode === games[3]) {
        for(let i=0;i<21;i++) if((i+frame)%23>3) content += rect(5+i%7*12,13+Math.floor(i/7)*6,11,4,['#94bedf','#cba4dc','#e5b07c'][i%3]);
        content += rect(8+(Math.sin(t*1.2)+1)*26,52,22,3,'#b1ddd1');
        content += `<circle cx="${8+(t*23)%80}" cy="${34+Math.abs(Math.sin(t*1.6))*15}" r="2" fill="#fff"/>`;
      } else {
        content += rect(8,12,80,42,'#eee9df');
        content += `<path d="M14 45Q28 10 44 35T80 26" pathLength="100" stroke-dasharray="100" stroke-dashoffset="${100-(t*12)%100}" fill="none" stroke="${actor.color}" stroke-width="2"/>`;
        content += `<circle cx="${20+(t*7)%60}" cy="30" r="2" fill="#46536a"/>`;
      }
    }
    return {mode, title, markup:`<g transform="translate(-48 -116)">${rect(0,0,96,58,'#192d40')}${content}</g>`};
  }
  return {state, render, games};
})();
