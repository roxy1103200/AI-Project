package com.cinema.ticketing.auth;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AuthServiceTest {

    @Mock
    private UserMapper userMapper;

    @Test
    void registerHashesPasswordAndLoginReturnsToken() {
        AuthService authService = new AuthService(userMapper);
        when(userMapper.findByUsername("alice")).thenReturn(null);

        UserAccount registered = authService.register("alice", "password-123", "13800000000");
        ArgumentCaptor<UserAccount> accountCaptor = ArgumentCaptor.forClass(UserAccount.class);
        verify(userMapper).insert(accountCaptor.capture());

        assertNotEquals("password-123", accountCaptor.getValue().getPasswordHash());
        assertTrue(accountCaptor.getValue().getPasswordHash().startsWith("$2a$"));

        when(userMapper.findByUsername("alice")).thenReturn(registered);
        AuthService.LoginResult result = authService.login("alice", "password-123");

        assertTrue(result.token() != null && !result.token().isBlank());
    }

    @Test
    void nonAdminCannotAccessAdminOperation() {
        AuthService authService = new AuthService(userMapper);
        when(userMapper.findByUsername("alice")).thenReturn(null);
        UserAccount registered = authService.register("alice", "password-123", null);
        when(userMapper.findByUsername("alice")).thenReturn(registered);
        String token = authService.login("alice", "password-123").token();

        assertThrows(RuntimeException.class, () -> authService.requireAdmin(token));
    }
}
