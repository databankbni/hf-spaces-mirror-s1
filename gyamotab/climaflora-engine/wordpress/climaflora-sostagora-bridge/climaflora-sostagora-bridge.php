<?php
/**
 * Plugin Name: ClimaFlora — Pont Sostagora
 * Description: Connexion à usage unique et synchronisation de l’accès ClimaFlora Plus pour les clients Sostagora.
 * Version: 1.0.0
 * Author: Shugo-An
 * Requires at least: 6.5
 * Requires PHP: 8.0
 */

if (!defined('ABSPATH')) {
    exit;
}

final class ClimaFlora_Sostagora_Bridge {
    private const VERSION = '1.0.0';
    private const ACCESS_META = 'sa_sostagora_access';
    private const CODE_PREFIX = 'cf_sostagora_code_';
    private const CODE_TTL = 120;
    private const FRONTEND_URL = 'https://shugoan.com/climaflora/';
    private const API_SYNC_URL = 'https://gyamotab-climaflora-engine.hf.space/api/v1/auth/sostagora/sync';
    private const CRON_HOOK = 'climaflora_sostagora_sync_user';
    private const BACKFILL_HOOK = 'climaflora_sostagora_backfill';

    public static function init(): void {
        add_action('rest_api_init', [self::class, 'register_routes']);
        add_action('admin_post_climaflora_sostagora_start', [self::class, 'start_login']);
        add_action('admin_post_nopriv_climaflora_sostagora_start', [self::class, 'require_login']);
        add_action('added_user_meta', [self::class, 'meta_changed'], 10, 4);
        add_action('updated_user_meta', [self::class, 'meta_changed'], 10, 4);
        add_action('deleted_user_meta', [self::class, 'meta_deleted'], 10, 4);
        add_action(self::CRON_HOOK, [self::class, 'sync_user'], 10, 2);
        add_action(self::BACKFILL_HOOK, [self::class, 'backfill']);
        add_shortcode('climaflora_sostagora_link', [self::class, 'shortcode']);
    }

    public static function activate(): void {
        if (!wp_next_scheduled(self::BACKFILL_HOOK)) {
            wp_schedule_single_event(time() + 10, self::BACKFILL_HOOK);
        }
    }

    public static function register_routes(): void {
        register_rest_route('climaflora/v1', '/sostagora/exchange', [
            'methods' => WP_REST_Server::CREATABLE,
            'callback' => [self::class, 'exchange'],
            'permission_callback' => '__return_true',
        ]);
        register_rest_route('climaflora/v1', '/status', [
            'methods' => WP_REST_Server::READABLE,
            'callback' => static fn() => rest_ensure_response([
                'service' => 'climaflora-sostagora-bridge',
                'version' => self::VERSION,
                'ready' => true,
            ]),
            'permission_callback' => '__return_true',
        ]);
    }

    public static function require_login(): void {
        auth_redirect();
        exit;
    }

    public static function start_login(): void {
        $user_id = get_current_user_id();
        if ($user_id <= 0) {
            self::require_login();
        }

        if (!self::has_access($user_id)) {
            wp_safe_redirect(add_query_arg('sostagora', 'forbidden', self::FRONTEND_URL));
            exit;
        }

        $code = self::issue_code($user_id);
        wp_safe_redirect(add_query_arg('sostagora_code', rawurlencode($code), self::FRONTEND_URL));
        exit;
    }

    public static function exchange(WP_REST_Request $request) {
        $code = trim((string)$request->get_param('code'));
        if (strlen($code) < 32 || strlen($code) > 256) {
            return new WP_Error('invalid_code', 'Code invalide ou expiré.', ['status' => 401]);
        }

        $key = self::CODE_PREFIX . hash('sha256', $code);
        $record = get_transient($key);
        delete_transient($key);
        if (!is_array($record) || empty($record['user_id'])) {
            return new WP_Error('expired_code', 'Code invalide ou expiré.', ['status' => 401]);
        }

        $user_id = absint($record['user_id']);
        $user = get_user_by('id', $user_id);
        if (!$user instanceof WP_User || !is_email($user->user_email)) {
            return new WP_Error('invalid_user', 'Compte Sostagora introuvable.', ['status' => 404]);
        }

        $level = self::access_level($user_id);
        return rest_ensure_response([
            'wordpress_user_id' => $user_id,
            'email' => strtolower($user->user_email),
            'active' => in_array($level, ['sostagora', 'sostagora_elite'], true),
            'access_level' => $level,
            'issued_at' => absint($record['issued_at'] ?? time()),
        ]);
    }

    public static function shortcode(): string {
        $url = admin_url('admin-post.php?action=climaflora_sostagora_start');
        return sprintf(
            '<a class="button climaflora-sostagora-link" href="%s">Accéder à ClimaFlora Plus</a>',
            esc_url($url)
        );
    }

    public static function meta_changed($meta_id, $user_id, $meta_key, $meta_value): void {
        if ($meta_key === self::ACCESS_META) {
            self::schedule_sync(absint($user_id), 0, 5);
        }
    }

    public static function meta_deleted($meta_ids, $user_id, $meta_key, $meta_value): void {
        if ($meta_key === self::ACCESS_META) {
            self::schedule_sync(absint($user_id), 0, 5);
        }
    }

    public static function sync_user(int $user_id, int $attempt = 0): void {
        $user = get_user_by('id', $user_id);
        if (!$user instanceof WP_User || !is_email($user->user_email)) {
            return;
        }

        $code = self::issue_code($user_id);
        $response = wp_remote_post(self::API_SYNC_URL, [
            'timeout' => 10,
            'headers' => ['Content-Type' => 'application/json'],
            'body' => wp_json_encode(['code' => $code]),
            'data_format' => 'body',
        ]);
        $status = is_wp_error($response) ? 0 : (int)wp_remote_retrieve_response_code($response);
        if ($status >= 200 && $status < 300) {
            delete_user_meta($user_id, 'climaflora_sostagora_sync_pending');
            update_user_meta($user_id, 'climaflora_sostagora_synced_at', current_time('mysql', true));
            return;
        }

        update_user_meta($user_id, 'climaflora_sostagora_sync_pending', current_time('mysql', true));
        if ($attempt < 4) {
            self::schedule_sync($user_id, $attempt + 1, 60 * (2 ** $attempt));
        }
    }

    public static function backfill(): void {
        $users = get_users([
            'fields' => 'ids',
            'meta_key' => self::ACCESS_META,
            'number' => 500,
        ]);
        foreach ($users as $index => $user_id) {
            self::schedule_sync((int)$user_id, 0, 5 + (int)$index);
        }
    }

    private static function schedule_sync(int $user_id, int $attempt, int $delay): void {
        if ($user_id <= 0) {
            return;
        }
        $args = [$user_id, $attempt];
        if (!wp_next_scheduled(self::CRON_HOOK, $args)) {
            wp_schedule_single_event(time() + max(1, $delay), self::CRON_HOOK, $args);
        }
    }

    private static function issue_code(int $user_id): string {
        $code = rtrim(strtr(base64_encode(random_bytes(32)), '+/', '-_'), '=');
        set_transient(
            self::CODE_PREFIX . hash('sha256', $code),
            ['user_id' => $user_id, 'issued_at' => time()],
            self::CODE_TTL
        );
        return $code;
    }

    private static function access_level(int $user_id): string {
        $level = (string)get_user_meta($user_id, self::ACCESS_META, true);
        return in_array($level, ['sostagora', 'sostagora_elite'], true) ? $level : 'none';
    }

    private static function has_access(int $user_id): bool {
        return self::access_level($user_id) !== 'none';
    }
}

ClimaFlora_Sostagora_Bridge::init();
register_activation_hook(__FILE__, [ClimaFlora_Sostagora_Bridge::class, 'activate']);
