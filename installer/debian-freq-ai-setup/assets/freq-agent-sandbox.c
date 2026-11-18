#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <linux/landlock.h>
#include <pwd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static int create_ruleset(const struct landlock_ruleset_attr *attr, size_t size, __u32 flags) {
    return syscall(SYS_landlock_create_ruleset, attr, size, flags);
}

static int add_path_rule(int ruleset_fd, const char *path, __u64 access) {
    int path_fd = open(path, O_PATH | O_CLOEXEC);
    if (path_fd < 0) {
        if (errno == ENOENT) return 0;
        perror(path);
        return -1;
    }
    struct landlock_path_beneath_attr rule = {.allowed_access = access, .parent_fd = path_fd};
    int result = syscall(SYS_landlock_add_rule, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, &rule, 0);
    close(path_fd);
    if (result < 0) perror("landlock_add_rule");
    return result;
}

static int member_of(gid_t wanted, gid_t primary) {
    if (primary == wanted) return 1;
    int count = getgroups(0, NULL);
    if (count < 0) return 0;
    gid_t *groups = calloc((size_t)count, sizeof(*groups));
    if (groups == NULL) return 0;
    int result = 0;
    if (getgroups(count, groups) == count) {
        for (int i = 0; i < count; i++) if (groups[i] == wanted) result = 1;
    }
    free(groups);
    return result;
}

int main(void) {
    const uid_t login_uid = getuid();
    const gid_t login_gid = getgid();
    struct passwd *account = getpwuid(login_uid);
    struct group *agents = getgrnam("freq-agents");
    if (login_uid == 0 || geteuid() != 0 || account == NULL || agents == NULL ||
        !member_of(agents->gr_gid, login_gid)) {
        fprintf(stderr, "freq sandbox: unauthorized or invalid launcher state\n");
        return 126;
    }

    /* Gate new entries during maintenance. CLOEXEC releases the shared lock
       only after the process has dropped to the agent UID, so the updater's
       process check cannot miss a login between approval and application. */
    int maintenance = open("/run/lock/freq-ai-maintenance.lock", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    struct stat maintenance_stat;
    if (maintenance < 0 || fstat(maintenance, &maintenance_stat) < 0 ||
        !S_ISREG(maintenance_stat.st_mode) || maintenance_stat.st_uid != 0 ||
        (maintenance_stat.st_mode & 0022) || flock(maintenance, LOCK_SH | LOCK_NB) < 0) {
        fprintf(stderr, "Agent maintenance is running or its lock is unavailable; try again later.\n");
        return 126;
    }

    int abi = create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 3) {
        fprintf(stderr, "freq sandbox: Landlock ABI 3 or newer is required\n");
        return 126;
    }
    __u64 handled = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_WRITE_FILE |
        LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR |
        LANDLOCK_ACCESS_FS_REMOVE_DIR | LANDLOCK_ACCESS_FS_REMOVE_FILE |
        LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_DIR |
        LANDLOCK_ACCESS_FS_MAKE_REG | LANDLOCK_ACCESS_FS_MAKE_SOCK |
        LANDLOCK_ACCESS_FS_MAKE_FIFO | LANDLOCK_ACCESS_FS_MAKE_BLOCK |
        LANDLOCK_ACCESS_FS_MAKE_SYM | LANDLOCK_ACCESS_FS_REFER |
        LANDLOCK_ACCESS_FS_TRUNCATE;
    if (abi >= 5) handled |= LANDLOCK_ACCESS_FS_IOCTL_DEV;
    const __u64 ro = LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR;
    const __u64 rx = ro | LANDLOCK_ACCESS_FS_EXECUTE;
    const __u64 rwx = rx | LANDLOCK_ACCESS_FS_WRITE_FILE |
        LANDLOCK_ACCESS_FS_REMOVE_DIR | LANDLOCK_ACCESS_FS_REMOVE_FILE |
        LANDLOCK_ACCESS_FS_MAKE_DIR | LANDLOCK_ACCESS_FS_MAKE_REG |
        LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO |
        LANDLOCK_ACCESS_FS_MAKE_SYM | LANDLOCK_ACCESS_FS_REFER |
        LANDLOCK_ACCESS_FS_TRUNCATE;
    __u64 device = ro | LANDLOCK_ACCESS_FS_WRITE_FILE;
    if (abi >= 5) device |= LANDLOCK_ACCESS_FS_IOCTL_DEV;

    struct landlock_ruleset_attr ruleset = {.handled_access_fs = handled};
    int ruleset_fd = create_ruleset(&ruleset, sizeof(ruleset), 0);
    if (ruleset_fd < 0) { perror("landlock_create_ruleset"); return 126; }
    const char *rx_paths[] = {"/usr", "/bin", "/sbin", "/lib", "/lib64", "/opt/freq-agents", NULL};
    const char *ro_paths[] = {"/etc", "/sys", "/run", "/home/freq-agents", "/var/lib/dpkg", NULL};
    const char *rwx_paths[] = {
        "/tmp", "/var/tmp", "/dev/shm", "/home/freq-agents/projects", "/home/freq-agents/session-data", "/run/freq-agents/tmux",
        "/var/lib/freq-agents/coms", "/var/lib/freq-agents/board",
        "/var/lib/freq-agents/discord/outbox", NULL
    };
    for (size_t i = 0; rx_paths[i]; i++) if (add_path_rule(ruleset_fd, rx_paths[i], rx) < 0) return 126;
    for (size_t i = 0; ro_paths[i]; i++) if (add_path_rule(ruleset_fd, ro_paths[i], ro) < 0) return 126;
    for (size_t i = 0; rwx_paths[i]; i++) if (add_path_rule(ruleset_fd, rwx_paths[i], rwx) < 0) return 126;
    /* Global shared SMB mounts live below root-owned /mnt. Execution stays denied. */
    if (add_path_rule(ruleset_fd, "/mnt", rwx & ~LANDLOCK_ACCESS_FS_EXECUTE) < 0) return 126;
    if (add_path_rule(ruleset_fd, "/proc", ro | LANDLOCK_ACCESS_FS_WRITE_FILE) < 0) return 126;
    if (add_path_rule(ruleset_fd, "/dev", device) < 0) return 126;

    char path[512];
    snprintf(path, sizeof(path), "/home/%s", account->pw_name);
    if (add_path_rule(ruleset_fd, path, rwx) < 0) return 126;
    snprintf(path, sizeof(path), "/home/freq-agents/staging/%s", account->pw_name);
    if (add_path_rule(ruleset_fd, path, rwx) < 0) return 126;
    snprintf(path, sizeof(path), "/run/user/%lu", (unsigned long)login_uid);
    if (add_path_rule(ruleset_fd, path, rwx) < 0) return 126;

    if (syscall(SYS_landlock_restrict_self, ruleset_fd, 0) < 0) {
        perror("landlock_restrict_self"); return 126;
    }
    close(ruleset_fd);
    if (setresgid(login_gid, login_gid, login_gid) < 0 ||
        setresuid(login_uid, login_uid, login_uid) < 0) {
        perror("privilege drop"); return 126;
    }
    if (geteuid() != login_uid || getegid() != login_gid) return 126;
    setenv("FREQ_SANDBOX", "1", 1);
    const char *command = getenv("SSH_ORIGINAL_COMMAND");
    if (command && *command) execl("/bin/bash", "bash", "-c", command, (char *)NULL);
    execl("/bin/bash", "-bash", (char *)NULL);
    perror("exec bash");
    return 126;
}
