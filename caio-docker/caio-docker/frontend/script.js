// ============================================================================
// Caio — fluxo de conversa para Business Partners
// A integração com os robôs Python fica em robos.js
// ============================================================================

const BOT_DELAY = 700;
let atendimentoIniciado = false;

// Estado da conversa
let conversationState = {
  step: 0,
  userName: '',
  userArea: '',
  isTyping: false
};

// Busca no backend os robôs que realmente existem
async function listarServicos() {
  try {
    const r = await fetch(`${API}/robos`).then(r => r.json());
    return r.success ? r.robos : [];
  } catch { return []; }
}

async function selectOption(roboId) {
  conversationState.step = 3;
  await showService(roboId);   // aciona o mesmo robô do card (ele já registra a mensagem)
}

const domElements = {
  chatBox: document.getElementById('chatBox'),
  chatMessages: document.getElementById('chatMessages'),
  userInput: document.getElementById('userInput'),
  chatTrigger: document.getElementById('chatBtn')
};

// --------------------------------------------------------------------------
// Tela de carregamento
// --------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  let progress = 0;
  const loadingText = document.getElementById('loadingText');
  const progressFill = document.getElementById('progressFill');
  const progressGlow = document.getElementById('progressGlow');

  const interval = setInterval(() => {
    progress += 10;
    progressFill.style.width = `${progress}%`;
    progressGlow.style.left = `${progress}%`;
    loadingText.textContent = `Carregando... ${progress}%`;

    if (progress >= 100) {
      clearInterval(interval);
      loadingText.textContent = 'Pronto para começar';
      setTimeout(() => {
        gsap.to('#loadingScreen', {
          opacity: 0, duration: 1,
          onComplete: () => { document.getElementById('loadingScreen').style.display = 'none'; }
        });
      }, 700);
    }
  }, 300);
});

// --------------------------------------------------------------------------
// Abertura / fechamento
// --------------------------------------------------------------------------
function toggleChat(show) {
  if (show) {
    domElements.chatBox.style.display = 'flex';
    gsap.fromTo(domElements.chatBox,
      { opacity: 0, scale: 0.3, rotationX: -90, transformPerspective: 600 },
      { opacity: 1, scale: 1, rotationX: 0, duration: 1, ease: 'power4.out' });
    domElements.chatTrigger.style.display = 'none';
    domElements.userInput.focus();
  } else {
    gsap.to(domElements.chatBox, {
      opacity: 0, scale: 0.3, rotationX: -90, duration: 0.6, ease: 'power4.in',
      onComplete: () => {
        domElements.chatBox.style.display = 'none';
        domElements.chatTrigger.style.display = 'flex';
      }
    });
  }
}

function startConversation() {
  if (atendimentoIniciado) return;
  atendimentoIniciado = true;
  toggleChat(true);
  appendBotMessage('Olá! Sou o Caio, assistente dos Business Partners. Como posso te chamar?');
  conversationState.step = 1;
}

// --------------------------------------------------------------------------
// Mensagens
// --------------------------------------------------------------------------
function appendBotMessage(msg, options = []) {
  const messageDiv = document.createElement('div');
  messageDiv.className = 'message bot-message';
  messageDiv.innerHTML = `<strong>CAIO:</strong> ${msg}`;

  if (options.length > 0) {
    const container = document.createElement('div');
    container.className = 'area-btn-container';
    options.forEach(option => {
      // Aceita string simples ou objeto do catálogo { id, nome }
      const id = typeof option === 'string' ? option : option.id;
      const rotulo = typeof option === 'string' ? option : option.nome;
      const button = document.createElement('button');
      button.className = 'area-btn';
      button.textContent = rotulo;
      button.onclick = () => selectOption(id);
      container.appendChild(button);
    });
    messageDiv.appendChild(container);
  }

  domElements.chatMessages.appendChild(messageDiv);
  scrollToBottom();
}

function appendUserMessage(msg) {
  const messageDiv = document.createElement('div');
  messageDiv.className = 'message user-message';
  messageDiv.innerHTML = `<strong>VOCÊ:</strong> ${sanitizeInput(msg)}`;
  domElements.chatMessages.appendChild(messageDiv);
  scrollToBottom();
}

// --------------------------------------------------------------------------
// Fluxo
// --------------------------------------------------------------------------
async function sendMessage() {
  const text = domElements.userInput.value.trim();
  if (!text) return;

  appendUserMessage(text);
  domElements.userInput.value = '';

  switch (conversationState.step) {
    case 1:
      conversationState.userName = sanitizeInput(text);
      showTypingIndicator();
      listarServicos().then(robos => {
        removeTypingIndicator();
        const div = document.createElement('div');
        div.className = 'message bot-message';
        div.innerHTML = `<strong>CAIO:</strong> Prazer, ${conversationState.userName}! ` +
                        `Estes são os serviços disponíveis hoje:`;
        const cont = document.createElement('div');
        cont.className = 'area-btn-container';
        robos.forEach(r => {
          const b = document.createElement('button');
          b.className = 'area-btn';
          b.textContent = r.nome;
          b.onclick = () => selectOption(r.id);
          cont.appendChild(b);
        });
        div.appendChild(cont);
        domElements.chatMessages.appendChild(div);
        scrollToBottom();
        conversationState.step = 2;
      });
      break;

    default:
      showTypingIndicator();
      listarServicos().then(robos => {
        removeTypingIndicator();
        appendBotMessage(
          'Ainda estou aprendendo a interpretar texto livre. Posso te ajudar com:',
          robos
        );
      });
  }
}

// --------------------------------------------------------------------------
// Utilitários
// --------------------------------------------------------------------------
function showTypingIndicator() {
  conversationState.isTyping = true;
  const typingDiv = document.createElement('div');
  typingDiv.className = 'typing-indicator';
  typingDiv.id = 'typingIndicator';
  typingDiv.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
  domElements.chatMessages.appendChild(typingDiv);
  scrollToBottom();
}

function removeTypingIndicator() {
  conversationState.isTyping = false;
  const indicator = document.getElementById('typingIndicator');
  if (indicator) indicator.remove();
}

function scrollToBottom() {
  domElements.chatMessages.scrollTop = domElements.chatMessages.scrollHeight;
}

function sanitizeInput(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function getAuthToken() {
  return localStorage.getItem('bradesco_auth_token') || '';
}