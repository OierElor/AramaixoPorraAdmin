async function get(path) {
  const res = await fetch(path);
  return res.json();
}

async function post(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

// Txapelketak
async function loadTxapelketak(){
  const list = document.getElementById('txapelketak-list');
  list.innerHTML = '';
  const items = await get('/api/txapelketak');
  items.forEach(it => {
    const li = document.createElement('li');
    li.textContent = `${it.Txapelketa_ID} — ${it.Izena} (${it.Urtea})`;
    list.appendChild(li);
  });
}

document.getElementById('txap-add').addEventListener('click', async ()=>{
  const iz = document.getElementById('txap-izena').value.trim();
  const ur = parseInt(document.getElementById('txap-urtea').value,10);
  if(!iz || !ur) return alert('Sartu izena eta urtea');
  await post('/api/txapelketak', { Izena: iz, Urtea: ur });
  document.getElementById('txap-izena').value='';
  document.getElementById('txap-urtea').value='';
  loadTxapelketak();
});

// Porralariak
async function loadPorralariak(){
  const list = document.getElementById('porra-list');
  list.innerHTML = '';
  const items = await get('/api/porralariak');
  items.forEach(it => {
    const li = document.createElement('li');
    li.textContent = `${it.Porralaria_ID} — ${it.Izena} (x${it['Zenbat Porra']})`;
    list.appendChild(li);
  });
}

document.getElementById('porra-add').addEventListener('click', async ()=>{
  const iz = document.getElementById('porra-izena').value.trim();
  if(!iz) return alert('Sartu izena');
  await post('/api/porralariak', { Izena: iz });
  document.getElementById('porra-izena').value='';
  loadPorralariak();
});

// Txirrindulariak
async function loadTxirrindulariak(){
  const list = document.getElementById('txirri-list');
  list.innerHTML = '';
  const items = await get('/api/txirrindulariak');
  items.forEach(it => {
    const li = document.createElement('li');
    li.textContent = `${it.Txirrindularia_ID} — ${it.Izena}`;
    list.appendChild(li);
  });
}

document.getElementById('txirri-add').addEventListener('click', async ()=>{
  const iz = document.getElementById('txirri-izena').value.trim();
  if(!iz) return alert('Sartu izena');
  await post('/api/txirrindulariak', { Izena: iz });
  document.getElementById('txirri-izena').value='';
  loadTxirrindulariak();
});

// Initial load
loadTxapelketak();
loadPorralariak();
loadTxirrindulariak();
