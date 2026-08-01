// ============================================================================
// Integração com os robôs Python: cards, menu de ações e upload de planilha
// Carregado DEPOIS de script.js
// ============================================================================

const API = '/api';

// Card (id do onclick no HTML) -> id do robô no catálogo Python
const MAPA_CARD_ROBO = {
  orcamento: 'orcamento',
  em_construcao: 'em_construcao'
};

// Robôs longos (Playwright, extrações pesadas) — usam job + polling
const ROBOS_ASSINCRONOS = [];

const POLL_INTERVALO_MS = 1500;
const POLL_MAX_TENTATIVAS = 200; // ~5 min

// Sessão do robô: qual está engatilhado e qual planilha ele vai usar
const sessaoRobo = {
  roboId: null,
  acaoPendente: null,   // ação escolhida antes de a planilha chegar
  arquivoId: null,
  nomeArquivo: null
};

// --------------------------------------------------------------------------
// Clique no card: engatilha o robô e pede a ação
// --------------------------------------------------------------------------
async function showService(card) {
  const roboId = MAPA_CARD_ROBO[card];
  if (!roboId) {
    appendBotMessage('Esse serviço ainda não tem robô associado.');
    return;
  }

  abrirChat();
  sessaoRobo.roboId = roboId;
  sessaoRobo.acaoPendente = null;

  appendUserMessage(`Abrir: ${card.replace('_', ' ')}`);
  await rodar(roboId, {}, card);   // sem "acao": o robô devolve o menu
}

// --------------------------------------------------------------------------
// Clique numa das alternativas do menu
// --------------------------------------------------------------------------
async function executarAcao(roboId, acao) {
  sessaoRobo.roboId = roboId;
  sessaoRobo.acaoPendente = acao;
  await rodar(roboId, { acao });
}

/** Executa o robô e renderiza o retorno no chat. */
async function rodar(roboId, extras, card) {
  showTypingIndicator();
  if (card) marcarCardOcupado(card, true);

  const params = Object.assign(coletarParametros(), extras);

  try {
    const resultado = ROBOS_ASSINCRONOS.includes(roboId)
      ? await executarRoboAssincrono(roboId, params)
      : await executarRobo(roboId, params);

    removeTypingIndicator();

    if (!resultado.success) {
      appendBotMessage(`Não consegui concluir: ${escaparHtml(resultado.error || 'erro desconhecido')}`);
      return;
    }
    renderizarResultado(resultado);
  } catch (erro) {
    removeTypingIndicator();
    console.error('Falha ao executar robô:', erro);
    appendBotMessage('O robô não respondeu. Tente novamente em alguns instantes.');
  } finally {
    if (card) marcarCardOcupado(card, false);
  }
}

function coletarParametros() {
  return {
    solicitante: conversationState.userName || '',
    area: conversationState.userArea || '',
    arquivo_id: sessaoRobo.arquivoId || ''
  };
}

function abrirChat() {
  if (!domElements.chatBox.style.display || domElements.chatBox.style.display === 'none') {
    atendimentoIniciado = true;
    toggleChat(true);
  }
}

// --------------------------------------------------------------------------
// Chamadas HTTP
// --------------------------------------------------------------------------
async function executarRobo(roboId, params) {
  const resposta = await fetch(`${API}/robos/${roboId}/executar`, {
    method: 'POST', headers: cabecalhos(), body: JSON.stringify(params)
  });
  return await resposta.json();
}

async function executarRoboAssincrono(roboId, params) {
  const criacao = await fetch(`${API}/robos/${roboId}/jobs`, {
    method: 'POST', headers: cabecalhos(), body: JSON.stringify(params)
  }).then(r => r.json());

  if (!criacao.success) return criacao;

  for (let i = 0; i < POLL_MAX_TENTATIVAS; i++) {
    await new Promise(r => setTimeout(r, POLL_INTERVALO_MS));
    const job = await fetch(`${API}/jobs/${criacao.job_id}`).then(r => r.json());
    if (job.status === 'concluido') return job;
    if (job.status === 'erro') return { success: false, error: job.error };
  }
  return { success: false, error: 'Tempo de espera esgotado.' };
}

function cabecalhos() {
  const h = { 'Content-Type': 'application/json' };
  const token = getAuthToken();
  if (token) h['Authorization'] = 'Bearer ' + token;
  return h;
}

// --------------------------------------------------------------------------
// Upload de planilha
// --------------------------------------------------------------------------
function abrirSeletorArquivo() {
  document.getElementById('inputArquivo').click();
}

async function enviarArquivo(input) {
  const arquivo = input.files && input.files[0];
  input.value = ''; // permite reenviar o mesmo arquivo depois
  if (!arquivo) return;

  abrirChat();
  appendUserMessage(`Planilha enviada: ${arquivo.name}`);
  showTypingIndicator();

  const form = new FormData();
  form.append('arquivo', arquivo);

  try {
    const token = getAuthToken();
    const resposta = await fetch(`${API}/upload`, {
      method: 'POST',
      headers: token ? { 'Authorization': 'Bearer ' + token } : {},
      body: form
    });
    const dados = await resposta.json();
    removeTypingIndicator();

    if (!dados.success) {
      appendBotMessage(`Não consegui usar esse arquivo: ${escaparHtml(dados.error)}`);
      return;
    }

    sessaoRobo.arquivoId = dados.arquivo_id;
    sessaoRobo.nomeArquivo = dados.nome_original;
    mostrarChipArquivo(dados.nome_original, dados.tamanho_kb);

    appendBotMessage(
      `Planilha recebida (${dados.tamanho_kb} KB). Colunas identificadas: ` +
      `<em>${dados.colunas.map(escaparHtml).join(', ')}</em>.`
    );

    // Se o usuário já tinha escolhido a ação, retoma de onde parou
    if (sessaoRobo.roboId && sessaoRobo.acaoPendente) {
      await rodar(sessaoRobo.roboId, { acao: sessaoRobo.acaoPendente });
    } else if (sessaoRobo.roboId) {
      await rodar(sessaoRobo.roboId, {});
    }
  } catch (erro) {
    removeTypingIndicator();
    console.error('Falha no upload:', erro);
    appendBotMessage('Não consegui enviar o arquivo. Tente novamente.');
  }
}

function mostrarChipArquivo(nome, kb) {
  const barra = document.getElementById('arquivoAtivo');
  barra.innerHTML =
    `<span class="chip-arquivo" title="${escaparHtml(nome)}">${escaparHtml(nome)} · ${kb} KB` +
    `<button class="chip-remover" onclick="removerArquivo()" aria-label="Remover planilha">&times;</button></span>`;
  barra.style.display = 'block';
}

function removerArquivo() {
  sessaoRobo.arquivoId = null;
  sessaoRobo.nomeArquivo = null;
  const barra = document.getElementById('arquivoAtivo');
  barra.innerHTML = '';
  barra.style.display = 'none';
  appendBotMessage('Planilha removida da sessão.');
}

// --------------------------------------------------------------------------
// Renderização das respostas do robô
// --------------------------------------------------------------------------
function renderizarResultado(resultado) {
  const d = resultado.dados || {};
  const roboId = resultado.robo;

  const cabecalho =
    `<div class="robo-titulo">${escaparHtml(d.titulo || '')}</div>` +
    (d.resumo ? `<div class="robo-resumo">${escaparHtml(d.resumo)}</div>` : '');
  const rodape = `<div class="robo-rodape">Robô ${escaparHtml(resultado.nome || roboId)} · ${resultado.duracao_ms} ms</div>`;

  // Menu de alternativas: precisa de botões com callback
  if (d.tipo === 'opcoes') {
    const div = document.createElement('div');
    div.className = 'message bot-message';
    div.innerHTML = `<strong>CAIO:</strong> ${cabecalho}<div class="robo-texto">${d.texto || ''}</div>`;

    const container = document.createElement('div');
    container.className = 'opcoes-container';
    d.opcoes.forEach(op => {
      const btn = document.createElement('button');
      btn.className = 'opcao-btn';
      btn.textContent = op.rotulo;
      btn.onclick = () => {
        container.querySelectorAll('.opcao-btn').forEach(b => b.disabled = true);
        btn.classList.add('opcao-escolhida');
        appendUserMessage(op.rotulo);
        executarAcao(roboId, op.acao);
      };
      container.appendChild(btn);
    });
    div.appendChild(container);
    domElements.chatMessages.appendChild(div);
    scrollToBottom();
    return;
  }

  // Pedido de planilha: botão que abre o seletor
  if (d.tipo === 'solicitar_arquivo') {
    const div = document.createElement('div');
    div.className = 'message bot-message';
    div.innerHTML = `<strong>CAIO:</strong> ${cabecalho}<div class="robo-texto">${d.texto || ''}</div>`;
    const btn = document.createElement('button');
    btn.className = 'opcao-btn opcao-destaque';
    btn.textContent = 'Escolher planilha';
    btn.onclick = abrirSeletorArquivo;
    div.appendChild(btn);
    domElements.chatMessages.appendChild(div);
    scrollToBottom();
    return;
  }

  let corpo = '';

  if (d.tipo === 'tabela') {
    if (!d.linhas || d.linhas.length === 0) {
      corpo = '<div class="robo-vazio">Nenhum registro encontrado.</div>';
    } else {
      const th = d.colunas.map(c => `<th>${escaparHtml(c)}</th>`).join('');
      const tr = d.linhas.map(l =>
        `<tr>${l.map(c => `<td>${escaparHtml(c)}</td>`).join('')}</tr>`).join('');
      corpo = `<div class="robo-tabela-wrap"><table class="robo-tabela">
                 <thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
    }
  } else if (d.tipo === 'kv') {
    const itens = Object.entries(d.itens || {});
    corpo = itens.length
      ? `<dl class="robo-kv">${itens.map(([k, v]) =>
          `<dt>${escaparHtml(k)}</dt><dd>${escaparHtml(v)}</dd>`).join('')}</dl>`
      : '<div class="robo-vazio">Sem dados para exibir.</div>';
  } else if (d.tipo === 'arquivo') {
    corpo = `<a class="robo-download" href="${d.url}" download>Baixar ${escaparHtml(d.nome_arquivo)}</a>`;
  } else {
    corpo = `<div class="robo-texto">${d.texto || ''}</div>`;
  }

  appendBotMessage(cabecalho + corpo + rodape + botaoVoltarMenu(roboId));
}

/** Depois de qualquer resultado, oferece voltar ao menu do mesmo robô. */
function botaoVoltarMenu(roboId) {
  if (!roboId) return '';
  return `<button class="opcao-btn opcao-menu" onclick="executarAcao('${roboId}','')">Outra opção</button>`;
}

function marcarCardOcupado(card, ocupado) {
  const el = document.querySelector(`.service-card[onclick*="'${card}'"]`);
  if (el) el.classList.toggle('card-ocupado', ocupado);
}

function escaparHtml(valor) {
  const div = document.createElement('div');
  div.textContent = valor == null ? '' : String(valor);
  return div.innerHTML;
}
