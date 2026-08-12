// Minimal pub-sub so any component can fire a toast without prop-drilling a
// callback through several layers. ToastContainer (mounted once in App)
// subscribes and renders whatever comes through.
let listeners = [];

export function showToast(message, type = "success") {
  listeners.forEach((fn) => fn({ id: Date.now() + Math.random(), message, type }));
}

export function subscribeToast(fn) {
  listeners.push(fn);
  return () => {
    listeners = listeners.filter((l) => l !== fn);
  };
}
