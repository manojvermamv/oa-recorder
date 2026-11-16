/* Android blocks getifaddrs() for apps; answer with loopback only. */
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <stdlib.h>
#include <string.h>
struct blk { struct ifaddrs ifa; struct sockaddr_in addr, mask; char name[4]; };
int getifaddrs(struct ifaddrs **out) {
    struct blk *b = calloc(1, sizeof *b);
    if (!b) return -1;
    strcpy(b->name, "lo");
    b->addr.sin_family = b->mask.sin_family = AF_INET;
    b->addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    b->mask.sin_addr.s_addr = htonl(0xff000000);
    b->ifa.ifa_name = b->name;
    b->ifa.ifa_flags = IFF_UP | IFF_LOOPBACK | IFF_RUNNING;
    b->ifa.ifa_addr = (struct sockaddr *)&b->addr;
    b->ifa.ifa_netmask = (struct sockaddr *)&b->mask;
    *out = &b->ifa;
    return 0;
}
void freeifaddrs(struct ifaddrs *ifa) { free(ifa); }
