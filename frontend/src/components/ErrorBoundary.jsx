import { Component } from "react";

// Catches render errors in any child so one bad view shows a recoverable
// message instead of a blank white page. Only class components can be error
// boundaries - React has no hook equivalent.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Dashboard error:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: "40px 26px", textAlign: "center" }}>
          <p style={{ fontWeight: 600, marginBottom: 8 }}>Something went wrong showing this.</p>
          <p style={{ color: "var(--ink-faint)", fontSize: 13, marginBottom: 16 }}>
            {this.state.error.message || "Unknown error."}
          </p>
          <button className="pager-btn" type="button" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
