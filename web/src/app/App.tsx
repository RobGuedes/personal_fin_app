import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router";
import { ToastProvider } from "../components/Toast";
import { Ajustes } from "../sections/ajustes/Ajustes";
import { Inicio } from "../sections/inicio/Inicio";
import { CategoryPage } from "../sections/panorama/CategoryPage";
import { Panorama } from "../sections/panorama/Panorama";
import { Patrimonio } from "../sections/patrimonio/Patrimonio";
import { Revisar } from "../sections/revisar/Revisar";
import { Transacoes } from "../sections/transacoes/Transacoes";
import { NotFound } from "./NotFound";
import { makeQueryClient } from "./queryClient";
import { Shell } from "./Shell";

const queryClient = makeQueryClient();

/** The route table; `extra` lets tests mount additional routes inside the shell. */
export function AppRoutes({ extra }: { extra?: ReactNode }) {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Inicio />} />
        <Route path="revisar" element={<Revisar />} />
        <Route path="transacoes" element={<Transacoes />} />
        <Route path="panorama" element={<Panorama />} />
        <Route path="panorama/categoria/:id" element={<CategoryPage />} />
        <Route path="patrimonio" element={<Patrimonio />} />
        <Route path="ajustes" element={<Ajustes />} />
        {extra}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
