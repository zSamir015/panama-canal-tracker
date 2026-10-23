import './App.css';

export function App() {
  return (
    <main className="app">
      <header className="app__header">
        <h1>Panama Canal Tracker</h1>
        <p>Buques del Canal de Panamá en tiempo real a partir de datos AIS.</p>
      </header>
      <section className="app__map" aria-label="Mapa en vivo">
        <p>El mapa en vivo llega en la Fase 4.</p>
      </section>
    </main>
  );
}
