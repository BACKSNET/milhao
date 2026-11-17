// Assinatura do Milhão Ouro pelo Mercado Pago.
// Ações (com login): "assinar" cria a assinatura no cartão e devolve o link de pagamento; "pix" gera um Pix
// de 30 dias (QR Code); "conferir_pix" vê se o Pix caiu; "cancelar" cancela a renovação do cartão;
// "excluir_conta" apaga a conta e os dados da pessoa (LGPD).
// Sem login, com ?webhook=1: aviso do Mercado Pago. A função não confia no aviso: busca a assinatura
// direto no Mercado Pago e só então atualiza a tabela "assinaturas".
// Segredos: MP_ACCESS_TOKEN (Mercado Pago). Opcionais: PRECO_OURO (padrão 9.90), SITE_URL.
const SB = Deno.env.get("SUPABASE_URL") ?? "";
const MP = Deno.env.get("MP_ACCESS_TOKEN") ?? "";
const PRECO = Number(Deno.env.get("PRECO_OURO") ?? "9.90");
const SITE = Deno.env.get("SITE_URL") ?? "https://milhao.pages.dev/";
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (corpo: unknown, status = 200) =>
  new Response(JSON.stringify(corpo), { status, headers: { ...CORS, "content-type": "application/json; charset=utf-8" } });

// chave do servidor (ignora as regras de acesso) para gravar a assinatura e apagar contas
function chaveServidor(): string {
  try {
    const ks = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") ?? "{}");
    const v = Object.values(ks)[0];
    if (v) return String(v);
  } catch (_) { /* sem chaves novas */ }
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
}
const servidor = () => {
  const k = chaveServidor();
  return { apikey: k, ...(k.startsWith("eyJ") ? { authorization: `Bearer ${k}` } : {}), "content-type": "application/json" } as Record<string, string>;
};

async function mp(caminho: string, metodo = "GET", corpo?: unknown, extra: Record<string, string> = {}) {
  const r = await fetch(`https://api.mercadopago.com${caminho}`, {
    method: metodo,
    headers: { authorization: `Bearer ${MP}`, "content-type": "application/json", ...extra },
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  const d = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, d };
}

async function lerAssinatura(uid: string) {
  const r = await fetch(`${SB}/rest/v1/assinaturas?select=*&user_id=eq.${uid}`, { headers: servidor() });
  const l = r.ok ? await r.json() : [];
  return l[0] ?? null;
}
async function gravarAssinatura(linha: Record<string, unknown>) {
  await fetch(`${SB}/rest/v1/assinaturas?on_conflict=user_id`, {
    method: "POST",
    headers: { ...servidor(), prefer: "resolution=merge-duplicates,return=minimal" },
    body: JSON.stringify({ ...linha, atualizado_em: new Date().toISOString() }),
  });
}
const ehOuro = (a: { plano?: string; valido_ate?: string } | null) => a?.plano === "ouro" && !!a.valido_ate && new Date(a.valido_ate) > new Date();

// lê a assinatura no Mercado Pago e copia a situação para a tabela
async function sincronizar(preId: string) {
  const { ok, d } = await mp(`/preapproval/${preId}`);
  if (!ok || !d?.external_reference) return null;
  const status = ({ authorized: "ativa", paused: "pausada", cancelled: "cancelada", pending: "pendente" } as Record<string, string>)[d.status] ?? String(d.status);
  const linha: Record<string, unknown> = { user_id: d.external_reference, plano: "ouro", status, mp_assinatura: preId };
  // ativa: vale até a próxima cobrança, com 3 dias de folga para o cartão passar (sem encurtar dias de Pix já pagos).
  // cancelada ou pausada: continua valendo até o fim do que já foi pago (não mexe na data)
  if (status === "ativa" && d.next_payment_date) {
    const atual = await lerAssinatura(String(d.external_reference));
    const ate = new Date(d.next_payment_date).getTime() + 3 * 864e5;
    linha.valido_ate = new Date(Math.max(ate, atual?.valido_ate ? new Date(atual.valido_ate).getTime() : 0)).toISOString();
  }
  await gravarAssinatura(linha);
  return linha;
}

// Pix aprovado: soma 30 dias de Ouro, uma única vez por pagamento
async function creditarPix(p: Record<string, any>) {
  if (p?.status !== "approved" || !p.external_reference || p.currency_id !== "BRL" || Number(p.transaction_amount) < PRECO - 0.001) return false;
  const uid = String(p.external_reference);
  const r = await fetch(`${SB}/rest/v1/pagamentos_pix?on_conflict=id`, {
    method: "POST",
    headers: { ...servidor(), prefer: "resolution=ignore-duplicates,return=representation" },
    body: JSON.stringify({ id: String(p.id), user_id: uid, valor: Number(p.transaction_amount) }),
  });
  if (!r.ok) throw new Error(`pagamentos_pix: ${r.status} ${await r.text()}`);
  if (!(await r.json()).length) return true;   // esse pagamento já tinha sido creditado
  const atual = await lerAssinatura(uid);
  if (atual?.status === "criador") return true;
  const base = Math.max(Date.now(), atual?.valido_ate ? new Date(atual.valido_ate).getTime() : 0);
  const cartaoAtivo = atual?.status === "ativa" && ehOuro(atual);
  await gravarAssinatura({ user_id: uid, plano: "ouro", status: cartaoAtivo ? "ativa" : "pix", valido_ate: new Date(base + 30 * 864e5).toISOString() });
  return true;
}

async function quem(req: Request) {
  const token = (req.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
  const apikey = req.headers.get("apikey") ?? Deno.env.get("SUPABASE_ANON_KEY") ?? "";
  const r = await fetch(`${SB}/auth/v1/user`, { headers: { authorization: `Bearer ${token}`, apikey } });
  return r.ok ? await r.json() : null;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  const url = new URL(req.url);
  try {
    // ---- aviso do Mercado Pago ----
    if (url.searchParams.has("webhook")) {
      if (!MP) return json({ ok: true });
      const corpo = await req.json().catch(() => ({}));
      const tipo = String(corpo?.type ?? url.searchParams.get("type") ?? url.searchParams.get("topic") ?? "");
      const id = String(corpo?.data?.id ?? url.searchParams.get("data.id") ?? url.searchParams.get("id") ?? "");
      if (!id) return json({ ok: true });
      if (tipo.includes("authorized_payment")) {
        const p = await mp(`/authorized_payments/${id}`);
        if (p.ok && p.d?.preapproval_id) await sincronizar(String(p.d.preapproval_id));
      } else if (tipo.includes("preapproval")) await sincronizar(id);
      else if (tipo === "payment") {
        const p = await mp(`/v1/payments/${id}`);
        if (p.ok && p.d?.payment_method_id === "pix") await creditarPix(p.d);
      }
      return json({ ok: true });
    }

    if (req.method !== "POST") return json({ erro: "metodo" }, 405);
    const usuario = await quem(req);
    if (!usuario?.id) return json({ erro: "sem_login" }, 401);
    const { acao, id: pedidoId } = await req.json().catch(() => ({}));

    if (acao === "assinar") {
      if (!MP) return json({ erro: "pagamentos_em_breve" }, 503);
      const atual = await lerAssinatura(usuario.id);
      if (ehOuro(atual) && (atual.status === "ativa" || atual.status === "criador")) return json({ erro: "ja_assinante" }, 409);
      const { ok, d } = await mp("/preapproval", "POST", {
        reason: "Milhão Ouro",
        external_reference: usuario.id,
        payer_email: usuario.email,
        back_url: `${SITE}#perfil`,
        status: "pending",
        auto_recurring: { frequency: 1, frequency_type: "months", transaction_amount: PRECO, currency_id: "BRL" },
      });
      if (!ok || !d?.init_point) return json({ erro: "mp", detalhe: d?.message ?? d?.error ?? "" }, 502);
      await gravarAssinatura({ user_id: usuario.id, plano: "ouro", status: ehOuro(atual) ? atual.status : "pendente", mp_assinatura: d.id });
      return json({ link: d.init_point });
    }

    if (acao === "pix") {
      if (!MP) return json({ erro: "pagamentos_em_breve" }, 503);
      const atual = await lerAssinatura(usuario.id);
      if (ehOuro(atual) && (atual.status === "ativa" || atual.status === "criador")) return json({ erro: "ja_assinante" }, 409);
      // o código vale 30 minutos (horário de Brasília no formato que o Mercado Pago pede)
      const expira = new Date(Date.now() + 30 * 60e3 - 3 * 3600e3).toISOString().replace("Z", "-03:00");
      const { ok, d } = await mp("/v1/payments", "POST", {
        transaction_amount: PRECO,
        description: "Milhão Ouro - 30 dias",
        payment_method_id: "pix",
        payer: { email: usuario.email },
        external_reference: usuario.id,
        notification_url: `${SB}/functions/v1/assinatura?webhook=1`,
        date_of_expiration: expira,
      }, { "X-Idempotency-Key": crypto.randomUUID() });
      const t = d?.point_of_interaction?.transaction_data;
      if (!ok || !t?.qr_code) return json({ erro: "mp", detalhe: d?.message ?? d?.error ?? "" }, 502);
      return json({ id: String(d.id), copia_e_cola: t.qr_code, qr_base64: t.qr_code_base64 ?? "", valor: PRECO });
    }

    if (acao === "conferir_pix") {
      if (!MP) return json({ erro: "pagamentos_em_breve" }, 503);
      if (!/^\d+$/.test(String(pedidoId ?? ""))) return json({ erro: "id" }, 400);
      const { ok, d } = await mp(`/v1/payments/${pedidoId}`);
      if (!ok || String(d?.external_reference) !== usuario.id) return json({ erro: "nao_encontrado" }, 404);
      if (d.status === "approved") await creditarPix(d);
      return json({ status: d.status, assinatura: d.status === "approved" ? await lerAssinatura(usuario.id) : null });
    }

    if (acao === "cancelar") {
      const atual = await lerAssinatura(usuario.id);
      if (!atual?.mp_assinatura) return json({ erro: "sem_assinatura" }, 404);
      if (!MP) return json({ erro: "pagamentos_em_breve" }, 503);
      const r = await mp(`/preapproval/${atual.mp_assinatura}`, "PUT", { status: "cancelled" });
      if (!r.ok) return json({ erro: "mp", detalhe: r.d?.message ?? "" }, 502);
      await sincronizar(atual.mp_assinatura);
      return json({ assinatura: await lerAssinatura(usuario.id) });
    }

    if (acao === "atualizar") {
      const atual = await lerAssinatura(usuario.id);
      if (MP && atual?.mp_assinatura) await sincronizar(atual.mp_assinatura);
      return json({ assinatura: await lerAssinatura(usuario.id) });
    }

    if (acao === "excluir_conta") {
      const atual = await lerAssinatura(usuario.id);
      if (MP && atual?.mp_assinatura && atual.status !== "cancelada") await mp(`/preapproval/${atual.mp_assinatura}`, "PUT", { status: "cancelled" });
      const h = servidor();
      await fetch(`${SB}/storage/v1/object/avatares`, { method: "DELETE", headers: h, body: JSON.stringify({ prefixes: [`${usuario.id}/foto.jpg`] }) });
      await fetch(`${SB}/rest/v1/perfis?id=eq.${usuario.id}`, { method: "DELETE", headers: h });
      const r = await fetch(`${SB}/auth/v1/admin/users/${usuario.id}`, { method: "DELETE", headers: h });
      if (!r.ok) return json({ erro: "falha", detalhe: await r.text() }, 500);
      return json({ ok: true });
    }

    return json({ erro: "acao" }, 400);
  } catch (e) {
    return json({ erro: "falha", detalhe: String(e) }, 500);
  }
});
