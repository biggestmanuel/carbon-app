/**
 * axios does not know about the two custom fields the API layer attaches to a
 * request config. Declaring them here keeps `skipSessionExpiry` and `_retried`
 * type-safe instead of needing casts at every call site.
 */
import "axios";

declare module "axios" {
  export interface AxiosRequestConfig {
    /**
     * Set on requests whose 401 is an expected answer rather than an expired
     * session, so the interceptor does not trigger a logout.
     */
    skipSessionExpiry?: boolean;
    /**
     * Set on the single replay of a request after a refresh. Without it, a
     * server that keeps answering 401 makes the retry recurse until the tab
     * runs out of memory.
     */
    _retried?: boolean;
  }

  export interface InternalAxiosRequestConfig {
    skipSessionExpiry?: boolean;
    _retried?: boolean;
  }
}
