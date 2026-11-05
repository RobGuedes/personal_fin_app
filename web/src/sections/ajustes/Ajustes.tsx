import { t } from "../../i18n/pt-BR";
import { Aparencia } from "./Aparencia";
import { Auditoria } from "./Auditoria";
import { Lancamentos } from "./Lancamentos";
import { Orcamentos } from "./Orcamentos";
import { Regras } from "./Regras";
import { Sincronizacao } from "./Sincronizacao";
import "./ajustes.css";

export function Ajustes() {
  return (
    <section className="ajustes">
      <h1>{t.settings.title}</h1>
      <Sincronizacao />
      <Auditoria />
      <Regras />
      <Orcamentos />
      <Lancamentos />
      <Aparencia />
    </section>
  );
}
